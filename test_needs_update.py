import sys
from pathlib import Path
sys.path.insert(0, str(Path("server").resolve()))
from src.parser import parse_file
from src.mapping import todo_to_gtask_body
from src.sync_obs_to_gt import _task_needs_update
from src.gtasks import GoogleApiBackend
from src.config import Config
from src.db import initialize, connect
import sqlite3

def run():
    cfg = Config.load("server/config/config.yaml")
    backend = GoogleApiBackend(
        credentials_file=cfg.google.credentials_file,
        token_file=cfg.google.token_file,
        scopes=cfg.google.scopes,
    )
    # just pick one file, say 'todo-マイタスク.md'
    # we don't know the exact path but it's in main-dir as seen in the traceback
    vault_dir = Path("/home/megane/obsidian/main-dir")
    f = vault_dir / "todo-マイタスク.md"
    if not f.exists():
        print(f"File not found: {f}")
        return
    
    todos = parse_file(f)
    print(f"Parsed {len(todos)} todos")
    
    # get remote tasklist
    tasklists = backend.list_tasklists()
    tl_id = None
    for tl in tasklists:
        if tl.title == "マイタスク":
            tl_id = tl.id
            break
    if not tl_id:
        print("Tasklist not found")
        return
        
    print(f"Tasklist ID: {tl_id}")
    tasks = backend.list_tasks(tl_id, show_completed=True, show_hidden=True)
    remote_index = {t["id"]: t for t in tasks}
    
    needs_update_count = 0
    for todo in todos:
        if todo.gtasks_id and todo.gtasks_id in remote_index:
            body = todo_to_gtask_body(todo)
            remote = remote_index[todo.gtasks_id]
            if _task_needs_update(body, remote):
                needs_update_count += 1
                print(f"Needs update: {todo.title}")
                for key in ("title", "status", "notes", "due", "completed"):
                    v_body = body.get(key)
                    v_remote = remote.get(key)
                    if v_body != v_remote:
                        print(f"  Mismatch in {key}:")
                        print(f"    Body:   {repr(v_body)}")
                        print(f"    Remote: {repr(v_remote)}")

    print(f"Total needs update: {needs_update_count} out of {len(todos)}")

if __name__ == '__main__':
    run()
