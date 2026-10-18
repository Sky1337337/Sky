F6 ПОШУК — DIRECT INPUT TEST

F6 fills only four upper search inputs using Windows UI Automation
ValuePattern (not typing, not Ctrl+V, not clicking in a field).
It verifies all four values before clicking Find.
If Edge doesn't expose writable ValuePattern, F6 stops safely.
The 'Тип особи' dropdown is never selected or modified by F6.
Other F6 behavior and F7 remain unchanged.

Run: py main.py
On failure, send the exact error text from the program.
