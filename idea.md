# Sobre la app

Las apps que existen en Uruguay no resuelven algunos de los problemas que yo estaba experimentando.

En particular, los bancos en Uruguay no ofrecen APIs -> las aplicaciones que existen, no funcionan con los bancos.

Yo quería una app que automatizara lo más posible las cosas.

# Features

## Automatizar la ingesta de transacciones cuando sea possible.

- VISA te envia mails después de cada transacción, entonces nostros queremos poder automatáticamente procesar y agregar estos gastos.

- Splitwise, si ofrece una API, entonces queremos automatáticamente agregar todos los gastos en splitwise a la aplicación

## Facilidad de agregar gastos a mano

- Quiero poder copiar y pegar transaciones desde la página de cualquier banco en Uruguay y subirlas a la aplicación de forma fácil.

## Quiero poder especificiar el balance de las cuentas / tarjetas con periodos arbitrarios

- Quiero poder especificar en que fecha cierran las tarjetas y poder ver los gastos en esas fechas.

- Quiero poder "sobreescribr" el valor de las cuentas que tengo, por ejemplo, a principio de mes.

- Quiero poder especificar el tipo de cambio que estoy usando tan frencuente como quiera. 

## Visualización de datos

- Yo voy a querer ver mis gatos por categoria, por rango de tiempo
- Quiero poder guardar algunas vistas que me gusten más
- Quiero poder especfificar un tope por categoría y ver cuanto me queda disponible
- Quiero poder ver gastos anuales, o por projecto, o etc. 

## Categorización

- Yo quiero poder catalogar un gasto y asignarle: una categoria (super, resturante, ute, etc.), el payeee (tienda inglesa, ute, la pasiva), y un proyecto (vacaciones en santa teresa)

- Categoria y "payee" se asignan de forma "automática" y se van aprendiendo. 

- El proyecto lo asigno a mano, pero me permite separar gastos que generalmente están en distintas categorias.


## Usuarios

- Un usuario tiene que poder registrse y hacer su "setup" (agregar bancos, split, etc)
- Un usuario tiene que poder subir gastos
- Un usuario tiene que poder clasificar su gastos
- Un usuario tiene que poder ver sus gastos de forma util

## Extras

- Copiar y pegar no funciona en mobile, entonces vamos que que usar screenshots y usar AI para detectar que es cada cosa. 

# Plataformas

- Web para empezar
- Mobile para seguir


# Plan de implementación

1. Vamos a usar FastAPI para el backend
2. Vamos a usar HTMX para el frontend
3. Vamos a usar Celery para las tareas que se ejecuten en el background
4. Vamos a usar sqlite para la base de datos
5. Vamos a usar pydantic models + sqlaclhecmy para manejar los models y la base de datos