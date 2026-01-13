
Queremos procesar transaciones desde imagenes al igual que desde copy paste de bancos.

Para procesar imagenes vamos a usar llamacloud y su API. yo te voy a dar el codigo que dado el path the una imagen local, devuelve un pydantic model que debemos procesar y guardar como transaccion.

Coass que tenemos que implementar:

a) Los usuarios tienen que poder subir imagens o copiarlas del clipboard (esto tienen que funcionar en mobile tambien).
Los usuarios tienen que poder subir varias imagenes antes de procesar todo

b) Cuando las imagenes están listas, se llama en celery inmediatemente a la funcion (await process_image_with_llamacloud) que toma el path de todas las imagenes y devuelve un model de pydantic

c) transformamos el modelo de pydantic en una transaccion le agregmaos los campos que sean necesirios (la funente la agregamos nosotros igual que cuando agregamos transacciones copiando y pegnandi), se las mostramos al usuario para que valide (mostrar repetidas) y luego agregamos.


OBS: necesito que dejes el codigo de process_image_with_llamacloud vacio para que yo lo complete. 