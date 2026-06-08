Ich würde eigentlich eine Datei-orientierte Version (s. src/file_set_GPSIFD.py) präferieren aber da OpenStreetMap einen bestimmten Header verlangt, der im Datei-Ansatz fehlt, werden manche Kacheln nicht geladen, was unschön ist und im Zweifelsfall dazu führt, dass man eine Position nicht auswählen kann.

Dieses Problem tritt in der Flask-Variante nicht auf. Deswegen ist das diejenige, die funktioniert.


---

streamlit: Setzt Karte zurück, wenn man neues Foto auswählt -> doof
flask-fetch: perfekt
