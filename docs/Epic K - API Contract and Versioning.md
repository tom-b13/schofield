7.1.27
Title: Guard file has no module-scope DB driver imports (static AST check)
Purpose: Prove that app/guards/precondition.py does not import psycopg2 (or submodules) at module scope, ensuring the guard is DB-free at import time.
Test Data: Source path: app/guards/precondition.py. Static analysis via AST of top-level Import/ImportFrom nodes. Denylist: psycopg2 (any submodule).
Mocking: None. This is a static structural inspection of the real file; mocking would invalidate the result.
Assertions: (1) No module-scope Import or ImportFrom references psycopg2 or any psycopg2.*; (2) If any such import exists, the test fails and reports offending line numbers; (3) No dynamic import disguises at module scope (e.g., __import__("psycopg2")).
AC-Ref: 6.1.18; EARS: U19.

7.1.28
Title: Guard file has no module-scope repository imports (static AST check)
Purpose: Ensure app/guards/precondition.py avoids importing repository layers at module scope, keeping the guard isolated from persistence concerns.
Test Data: Source path: app/guards/precondition.py. Static analysis via AST of top-level Import/ImportFrom nodes. Denylist pattern: app.logic.repository_* (any repo module).
Mocking: None. Static code inspection only.
Assertions: (1) No module-scope Import/ImportFrom targets any module matching app.logic.repository_*; (2) If any such import exists, the test fails and reports offending line numbers; (3) No indirect module-scope imports of repositories via wildcard or alias (e.g., from app.logic import repository_answers as repo).
AC-Ref: 6.1.18; EARS: U19.
