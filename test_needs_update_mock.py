from server.src.mapping import todo_to_gtask_body
from server.src.sync_obs_to_gt import _task_needs_update
from server.src.parser import Todo

def run():
    # Case 1: Completed task without completed_at
    todo = Todo(
        title="Test Task",
        completed=True,
        completed_at=None,
        gtasks_id="T001"
    )
    body = todo_to_gtask_body(todo)
    
    remote = {
        "id": "T001",
        "title": "Test Task",
        "status": "completed",
        "completed": "2026-05-06T00:00:00.000Z"
    }
    
    needs = _task_needs_update(body, remote)
    print(f"Case 1 (Completed without completed_at): Needs update = {needs}")
    if needs:
        for key in ("title", "status", "notes", "due", "completed"):
            if body.get(key) != remote.get(key):
                print(f"  Mismatch in {key}: Body: {body.get(key)}, Remote: {remote.get(key)}")

    # Case 2: Notes missing in body vs empty string in remote
    todo2 = Todo(
        title="Test Task 2",
        completed=False,
        notes=None,
        gtasks_id="T002"
    )
    body2 = todo_to_gtask_body(todo2)
    
    remote2 = {
        "id": "T002",
        "title": "Test Task 2",
        "status": "needsAction",
        "notes": ""
    }
    
    needs2 = _task_needs_update(body2, remote2)
    print(f"\nCase 2 (Notes None vs empty string): Needs update = {needs2}")
    if needs2:
        for key in ("title", "status", "notes", "due", "completed"):
            if body2.get(key) != remote2.get(key):
                print(f"  Mismatch in {key}: Body: {body2.get(key)}, Remote: {remote2.get(key)}")

if __name__ == '__main__':
    run()
