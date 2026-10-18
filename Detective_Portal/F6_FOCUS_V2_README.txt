F6 SAFE WINDOW FOCUS V2
- DetectivePortal minimizes itself before OCR; it waits 0.2s for the window to disappear.
- Edge fields are identified only in the top search row (4 Edit controls alongside the top Find button).
- F6 clicks the current edit location after Edge restores, verifies Edge is foreground and checks focus before typing.
- If focus cannot be verified, F6 stops without typing. It NEVER types into the Type of person dropdown.
- F7 and photo handling unchanged.
- Run: py main.py
- Test on a draft only. The legacy form may react to Enter and browser security policies.
