import textwrap
from datetime import datetime
from functools import reduce

from app.db import db
from marshmallow import Schema, fields, missing
from sqlalchemy import Enum
from flask import current_app as app
from sqlalchemy.orm.attributes import InstrumentedAttribute
from webargs import ValidationError
import enum

from app.db.models.user import User


class StateEnum(enum.Enum):
    initial = 0
    active = 1
    completed = 2
    reopened = 3

class PriorityEnum(enum.Enum):
    low = 0
    medium = 1
    high = 2

class TodoSchema(Schema):
    owner = fields.String(required=True)
    submitter = fields.String(required=True)
    todo = fields.String(required=True)
    priority = fields.String(required=True)
    state = fields.String(required=True)
    task_id = fields.String(required=True)
    createtime = fields.DateTime()
    due = fields.DateTime(allow_none=True)
    mtime = fields.DateTime(dump_default=None)
    timesmodified = fields.Integer()
    isgroupitem = fields.Boolean()

    # class Meta:
    #     fields = ("url",)

# Create Todo schema in todo table
# Table will be initialised when app is started
# Refer app.__init__.py - db.create_all()
class Todo(db.Model):
    __tablename__ = 'todo'
    __schema__ = TodoSchema
    id = db.Column(db.Integer, primary_key=True)
    owner = db.Column(db.String(25))
    submitter = db.Column(db.String(25), default=None)
    task = db.Column(db.String(250), default=None)
    priority = db.Column(Enum(PriorityEnum), default='low')
    state = db.Column(Enum(StateEnum), default='initial')
    task_id = db.Column(db.String(200), default=None)
    createtime = db.Column(db.DateTime, default=None)
    due = db.Column(db.DateTime, default=None)
    dtime = db.Column(db.DateTime, default=None)
    mtime = db.Column(db.DateTime, default=None)
    timesmodified = db.Column(db.Integer, default=0)
    isgroupitem = db.Column(db.Boolean, default=False)

    @classmethod
    def fetch_tasks(cls, user, custom_fields=False):

        fetch = app.session.query(Todo.owner, Todo.submitter, Todo.task, Todo.priority,
                                  Todo.state, Todo.task_id, Todo.createtime, Todo.due, Todo.mtime,
                                  Todo.timesmodified).filter(
            Todo.owner == user,
            Todo.dtime.is_(None)
        ).all()

        tasks = []
        for task in fetch:
            task = task._asdict()
            tasks.append(task)

        return tasks

    @classmethod
    def _make_field_list(cls, joined_tables=[], blacklist=[], whitelist=[]):
        """
        One-stop function for finding and building a list of fields for querying on
        """
        # Whitelist overrides any exclusions
        if whitelist:
            fields = [
                v for k, v in cls.__dict__.items() if (
                                                              k == 'id' or k.endswith('_id')) and isinstance(
                    v, InstrumentedAttribute)]
            join_fields = []
            for field_name in whitelist:
                try:
                    field = getattr(cls, field_name)
                except AttributeError:
                    field = None

                if field:
                    fields.append(field)
                else:
                    # If we don't find a match here, it may be a table from a
                    # joined table
                    join_fields.append(field_name)

            if joined_tables and join_fields:
                try:
                    # Match fields from names based on <table name>_<field
                    # name> pattern
                    fields += [
                        getattr(table, x[len(table.__tablename__) + 1:]).label(x)
                        for table in joined_tables for x in join_fields
                        if x.startswith(table.__tablename__ + '_')
                    ]
                except AttributeError as e:
                    print(str(e))
                    raise ValidationError("Invalid Field Supplied", 400)
        else:  # No whitelist
            fields = unpack_fields(cls, join=False, excluded_fields=blacklist)
            if joined_tables:
                # Combine fields from all joined tables into one list
                fields = reduce(
                    lambda x, y: x + unpack_fields(y, True, blacklist),
                    joined_tables, fields
                )
        return fields

    @classmethod
    def _fetch_all_where(cls, *where, joined_tables=[], excluded_fields=[], whitelist=[]):
        for table in joined_tables:
            if hasattr(table, 'dtime'):
                where = where + (table.dtime.is_(None),)
        fields = cls._make_field_list(
            joined_tables, excluded_fields, whitelist)
        query = app.session.query(*fields)
        results = query.filter(*where).all()
        results = [row._asdict() for row in results]
        if 'task_id' not in excluded_fields:
            results = sanitise_task_id(results)
        return results

    @classmethod
    def _fetch_all(
            cls,
            filters,
            joined_tables=[],
            excluded_fields=[],
            whitelist=[],
            order_by=None):
        """
        Query multiple rows from the database
        """
        # Get rid of missing params
        filters = {k: v for k, v in filters.items() if v is not missing}

        # Get the fields from the main table
        fields = cls._make_field_list(
            joined_tables, excluded_fields, whitelist)

        # Create a base query for the main table
        query = app.session.query(*fields).filter_by(**filters)

        # If there are any joined tables, add them to the query
        for table in joined_tables:
            try:
                query = query.join(table)
                if hasattr(table, 'dtime'):
                    query = query.filter(table.dtime.is_(None))
            except Exception:
                raise ValidationError(
                    "Must choose at least one field from main table", 400)
        results = query.all()
        return [row._asdict() for row in results]

    @classmethod
    def get_reportees_tasks(cls, user):
        tasks = app.session.query(Todo.owner,
                                  Todo.task_id,
                                  Todo.task,
                                  Todo.state,
                                  Todo.priority,
                                  Todo.createtime,
                                  Todo.due,
                                  Todo.timesmodified,
                                  Todo.isgroupitem,
                                  User.name
                                  ).join(User,
                                         Todo.owner == User.username
                                         ).filter(Todo.submitter == user,
                                                  Todo.owner != user,
                                                  User.manager_id == user,
                                                  Todo.dtime.is_(None)
                                                  ).all()

        results = [row._asdict() for row in tasks]
        results = sanitise_task_id(results)
        task_dict_group = dict()
        task_dict_individual = dict()
        for task in results:
            owner = task['owner']
            ownername = task['name']
            groupitem = task['isgroupitem']
            task['state'] = task['state'].name
            task['priority'] = task['priority'].name
            del task['owner']
            del task['isgroupitem']
            del task['name']

            if groupitem:
                if task['task_id'] in task_dict_group:
                    task_dict_group[task['task_id']]['belongs to'] += f",\n{ownername} ({owner})"
                else:
                    task_dict_group[task['task_id']] = task
                    task_dict_group[task['task_id']]['belongs to'] = f"{ownername} ({owner})"
            else:
                if owner in task_dict_individual:
                    task_dict_individual[owner].append(task)
                else:
                    task_dict_individual[owner] = [task]

        return task_dict_group, task_dict_individual


def unpack_fields(obj, join=False, excluded_fields=[]):
    """
    Takes a SQLAlchemy Table object and returns field items.
    If join is True, include the table name in the field name
    (to distinguish fields from joined table with the same name as the parent table)
    """

    def labeler(x):
        return x.label('{}_{}'.format(obj.__tablename__, x.key)) if join else x

    def strip_tablename(x):
        return str(x).replace("{}.".format(obj.__tablename__), "")

    fields = []
    for x in obj.__table__.columns:
        x = strip_tablename(x)
        if x not in excluded_fields:
            fields.append(labeler(getattr(obj, x)))
    return fields

def sanitise_task_id(data):
    for x in data:
        x['task_id'] = x['task_id'].split('_', 1)[1]
    return data