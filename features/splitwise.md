
Queremos agregar una integración con splitwise.

1) El usuario debería tener un boton que haciendo click lo lleve a hacer oauth con splitwise y genere un token que guardamos en la base de datos
2) Periodicamente (o si hay un url callback) simpre que haya una nueva transaccion vamos a agregarla. Si el usuario debe, agregamos el monto que debe, y si el usario fue el que pago, agregamos el monto que le deben (no lo que pago).
3) la descrpción de la transacción debería ser el mensaje del gasto, y la source debería ser "split:<nombre grouo>" o "split:<nombre persona>".
4) el processamiento de esto debería pasar en celery.

Docs the la api de splitwise acá: https://dev.splitwise.com/#section/Terms-of-Use/TERMS-OF-USE

