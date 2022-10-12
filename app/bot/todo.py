from datetime import datetime
from sqlalchemy import exc
from app.db.models.todo import Todo
from flask import current_app as app
from tabulate import tabulate

class TodoManager:
    def __init__(self, user):
        self.user = user
        self.tasks = Todo.fetch_tasks(user['username'])
        self.user_tasks = [x for x in self.tasks if x['submitter'] == user['username']]
        self.manager_tasks = [x for x in self.tasks if x['submitter'] != user['username']]

    def add_task(self, task, owner, submitter):
        newdata = Todo(owner=owner, submitter=submitter, todo_item=task['task'],
                       priority=task['priority'], state=task['state'], taskid=f'{submitter}_{task["task_id"]}',
                       createtime=datetime.now(), duetime=task['due'], dtime=None,
                       mtime=datetime.now(), timesmodified=0)

        app.session.add(newdata)

        try:
            app.session.commit()
        # If there is any exception during commit, the session should rollback
        except exc.IntegrityError:
            app.session.rollback()
        except Exception as e:
            app.session.rollback()

    def delete_task(self, task_id):
        task_id = self.user['username'] + '_' + task_id
        fetch = app.session.query(Todo).filter(
            Todo.taskid == task_id,
            Todo.dtime.is_(None)
        ).all()
        if not fetch:
            return None
        fetch = fetch[0]
        setattr(fetch, 'dtime', fetch.dtime or datetime.now())

        try:
            app.session.commit()
        except Exception as e:
            # If any exception during the commit, session should rollback
            app.session.rollback()
            return False
        return True

    def _get_markdown_table(self):
        tasks = Todo._fetch_all_where(Todo.owner == self.user['username'], Todo.dtime.is_(None), excluded_fields=['mtime', 'id', 'dtime'])
        self_tasks = [x for x in tasks if x['owner'] == x['submitter']]
        manager_tasks = [x for x in tasks if x not in self_tasks]

        for x in self_tasks:
            del x['owner']
            del x['submitter']
            x['priority'] = x['priority'].name
            x['state'] = x['state'].name

        for x in manager_tasks:
            del x['owner']
            del x['submitter']
            x['priority'] = x['priority'].name
            x['state'] = x['state'].name

        self_task_table = tabulate(self_tasks, headers='keys', tablefmt="github")
        manager_task_table = tabulate(manager_tasks, headers='keys', tablefmt="github")
        return self_task_table, manager_task_table

