from functools import wraps
from io import BytesIO
from datetime import datetime
import os
import re
from urllib.parse import quote_plus
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, make_response, session, g
)
from werkzeug.utils import secure_filename
from xhtml2pdf import pisa
from extensions import db
from models import Rol, Usuario, Cliente, Credito, Ruta, Factura, Producto

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_secreta_para_mensajes')

db_url = os.environ.get(
    'DATABASE_URL',
    'postgresql+psycopg://postgres:1234@localhost:5432/sistema_agricola'
)
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql+psycopg://', 1)
elif db_url.startswith('postgresql://'):
    db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
}

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'productos')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

ORIGEN_TIENDA = 'Sonsonate, El Salvador'
TARIFAS_ENVIO = {
    'Sonsonate Centro': 4.50,
    'Acajutla, Sonsonate': 8.00,
    'Izalco, Sonsonate': 6.50,
    'Armenia, Sonsonate': 7.50,
    'Nahuizalco, Sonsonate': 6.50,
    'Juayúa, Sonsonate': 9.00,
    'Santa Ana': 14.00,
    'San Salvador': 16.50,
}

db.init_app(app)


def archivo_imagen_permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def resolver_imagen_producto(nombre_base_o_archivo):
    if not nombre_base_o_archivo:
        return None
    ruta_directa = os.path.join(app.config['UPLOAD_FOLDER'], nombre_base_o_archivo)
    if os.path.isfile(ruta_directa):
        return nombre_base_o_archivo

    base_sin_ext = os.path.splitext(nombre_base_o_archivo)[0]
    for ext in ('jpg', 'jpeg', 'png', 'webp'):
        candidato = f"{base_sin_ext}.{ext}"
        if os.path.isfile(os.path.join(app.config['UPLOAD_FOLDER'], candidato)):
            return candidato
    return None


def construir_url_maps(destino):
    destino_limpio = destino if destino else ORIGEN_TIENDA
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(ORIGEN_TIENDA)}"
        f"&destination={quote_plus(destino_limpio)}"
        "&travelmode=driving"
    )


# --- PROTECCIÓN DE SESIÓN Y CACHÉ ---
@app.after_request
def agregar_cabeceras_no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.before_request
def cargar_usuario_actual():
    g.usuario = None
    usuario_id = session.get('usuario_id')
    if usuario_id:
        usuario = db.session.get(Usuario, usuario_id)
        if usuario and usuario.activo:
            g.usuario = usuario
        else:
            session.pop('usuario_id', None)
            session.pop('rol', None)


@app.context_processor
def inyectar_usuario():
    return {
        'usuario_actual': g.usuario,
        'resolver_imagen': resolver_imagen_producto,
        'origen_tienda': ORIGEN_TIENDA,
        'tarifas_envio': TARIFAS_ENVIO,
        'construir_url_maps': construir_url_maps
    }


def login_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if not g.usuario:
            flash('Debes iniciar sesión para acceder al sistema.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorador


def roles_requeridos(*roles_permitidos):
    def decorador(f):
        @wraps(f)
        def decorador_interno(*args, **kwargs):
            if not g.usuario:
                flash('Debes iniciar sesión para continuar.')
                return redirect(url_for('login'))
            nombre_rol = g.usuario.rol.nombre.upper() if g.usuario.rol else ''
            if nombre_rol not in roles_permitidos:
                flash('Acceso denegado: tu rol no tiene permiso para realizar esta acción.')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorador_interno
    return decorador


def inicializar_datos_base():
    db.create_all()

    for nombre_rol, desc in [
        ('ADMIN', 'Acceso total: catálogo, créditos, usuarios y operación'),
        ('VENDEDOR', 'Gestión de agricultores, facturación y rutas de entrega'),
        ('COMPRADOR', 'Consulta de catálogo, carrito de pedido, facturas y rutas'),
    ]:
        if not Rol.query.filter_by(nombre=nombre_rol).first():
            db.session.add(Rol(nombre=nombre_rol, descripcion=desc))
    db.session.commit()

    rol_admin = Rol.query.filter_by(nombre='ADMIN').first()
    if not Usuario.query.filter_by(username='admin').first():
        admin_user = Usuario(
            username='admin',
            nombre_persona='Administrador General',
            rol_id=rol_admin.id,
            activo=True
        )
        admin_user.set_password('admin123')
        db.session.add(admin_user)
        db.session.commit()

    if Producto.query.count() == 0:
        productos_iniciales = [
            Producto(nombre='SEMILLA MAÍZ HÍBRIDO ADV 8480 (50M)', categoria='Semilla', precio=48.50, stock=120, imagen='1.jpg'),
            Producto(nombre='SEMILLA MAÍZ HÍBRIDO DEKALB DK-390', categoria='Semilla', precio=54.00, stock=95, imagen='2.jpg'),
            Producto(nombre='SEMILLA MAÍZ CRIOLLO MEJORADO H-59', categoria='Semilla', precio=36.00, stock=140, imagen='3.jpg'),
            Producto(nombre='SEMILLA FRIJOL ROJO DE SEDA CENTA (25 LB)', categoria='Semilla', precio=32.00, stock=110, imagen='4.jpg'),
            Producto(nombre='SEMILLA FRIJOL NEGRO CALIMA (25 LB)', categoria='Semilla', precio=30.50, stock=85, imagen='5.jpg'),
            Producto(nombre='SEMILLA SORGO CENTA S-3 (20 KG)', categoria='Semilla', precio=28.00, stock=90, imagen='6.jpg'),
            Producto(nombre='SEMILLA ARROZ CENTA A-8 (40 KG)', categoria='Semilla', precio=42.00, stock=75, imagen='7.jpg'),
            Producto(nombre='SEMILLA TOMATE INDETERMINADO SHANTY (1000 SEM)', categoria='Semilla', precio=65.00, stock=40, imagen='8.jpg'),
            Producto(nombre='SEMILLA CHILE DULCE NATALY (1000 SEM)', categoria='Semilla', precio=58.00, stock=45, imagen='9.jpg'),
            Producto(nombre='SEMILLA PEPINO DIAMANTE F1 (500 SEM)', categoria='Semilla', precio=29.50, stock=60, imagen='10.jpg'),
            Producto(nombre='BLAZER 16 EW / 20 L', categoria='Insecticida', precio=435.00, stock=20, imagen='11.jpg'),
            Producto(nombre='BLAZER 16 EW / 1 LT', categoria='Insecticida', precio=24.50, stock=80, imagen='12.jpg'),
            Producto(nombre='KARATE ZEON 5 CS / 1 LT', categoria='Insecticida', precio=34.00, stock=70, imagen='13.jpg'),
            Producto(nombre='ENGEO 24.7 SC / 1 LT', categoria='Insecticida', precio=46.50, stock=55, imagen='14.jpg'),
            Producto(nombre='CONFIDOR 70 WG / 250 GR', categoria='Insecticida', precio=28.75, stock=65, imagen='15.jpg'),
            Producto(nombre='SEMILLA DE CEBOLLA AMARILLA (1000 SEM)', categoria='Semilla', precio=35.00, stock=75, imagen='16.jpg'),
            Producto(nombre='MELÓN CANTALOUPE (1000 SEM)', categoria='Semilla', precio=44.00, stock=55, imagen='17.jpg'),
            Producto(nombre='REPOLLO HÍBRIDO (1000 SEM)', categoria='Semilla', precio=38.50, stock=65, imagen='18.jpg'),
            Producto(nombre='ZANAHORIA 1028GJ (1000 SEM)', categoria='Semilla', precio=26.00, stock=85, imagen='19.jpg'),
            Producto(nombre='FERTILIZANTE NPK EQUILIBRADO K4T1 (25 KG)', categoria='Hidrosoluble', precio=52.00, stock=90, imagen='20.jpg'),
            Producto(nombre='CUMA', categoria='Herramientas', precio=14.50, stock=100, imagen='21.jpg'),
            Producto(nombre='AZADÓN', categoria='Herramientas', precio=16.00, stock=85, imagen='22.jpg'),
            Producto(nombre='BOMBA / ROCIADOR DE JARDÍN', categoria='Herramientas', precio=39.00, stock=45, imagen='23.jpg'),
            Producto(nombre='PALA', categoria='Herramientas', precio=18.50, stock=75, imagen='24.jpg'),
            Producto(nombre='TIJERAS DE PODAR', categoria='Herramientas', precio=13.75, stock=95, imagen='25.jpg'),
        ]
        db.session.add_all(productos_iniciales)
        db.session.commit()


# --- HELPERS DE CARRITO Y COMPRADOR ---
def obtener_carrito():
    return session.get('carrito', {})


def calcular_resumen_carrito():
    carrito = obtener_carrito()
    items = []
    total_general = 0.0
    total_unidades = 0

    for prod_id_str, cant in carrito.items():
        producto = db.session.get(Producto, int(prod_id_str))
        if producto and cant > 0:
            subtotal = round(producto.precio * cant, 2)
            total_general = round(total_general + subtotal, 2)
            total_unidades += cant
            items.append({
                'producto': producto,
                'cantidad': cant,
                'subtotal': subtotal
            })

    return items, total_general, total_unidades


def obtener_o_crear_cliente_comprador(usuario, telefono='', direccion=''):
    dui_sintetico = f"WEB-{usuario.id:06d}"
    cliente = Cliente.query.filter_by(dui=dui_sintetico).first()
    if not cliente:
        cliente = Cliente.query.filter_by(nombre=usuario.nombre_persona).first()
    if not cliente:
        cliente = Cliente(
            nombre=usuario.nombre_persona,
            dui=dui_sintetico,
            telefono=telefono or 'N/A',
            direccion=direccion or 'Compra en línea'
        )
        db.session.add(cliente)
        db.session.flush()
    else:
        cliente.nombre = usuario.nombre_persona
        if telefono:
            cliente.telefono = telefono
        if direccion:
            cliente.direccion = direccion
    return cliente


# --- AUTENTICACIÓN Y REGISTRO DE COMPRADOR ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.usuario:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        usuario = Usuario.query.filter_by(username=username).first()
        if usuario and usuario.activo and usuario.check_password(password):
            session['usuario_id'] = usuario.id
            session['rol'] = usuario.rol.nombre
            flash(f'Bienvenido, {usuario.nombre_persona} ({usuario.rol.nombre}).')
            return redirect(url_for('home'))
        else:
            flash('Usuario o contraseña incorrectos, o cuenta inactiva.')

    return render_template('login.html')


@app.route('/registro-comprador', methods=['GET', 'POST'])
def registro_comprador():
    if g.usuario:
        return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        nombre_persona = request.form['nombre_persona'].strip()
        password = request.form['password']

        if not username or not nombre_persona or len(password) < 4:
            flash('Completa todos los campos (contraseña de al menos 4 caracteres).')
            return redirect(url_for('registro_comprador'))

        if Usuario.query.filter_by(username=username).first():
            flash('Ese nombre de usuario ya existe. Elige otro.')
            return redirect(url_for('registro_comprador'))

        rol_comprador = Rol.query.filter_by(nombre='COMPRADOR').first()
        if not rol_comprador:
            rol_comprador = Rol(nombre='COMPRADOR', descripcion='Consulta de catálogo, carrito de pedido, facturas y rutas')
            db.session.add(rol_comprador)
            db.session.commit()

        nuevo_comprador = Usuario(
            username=username,
            nombre_persona=nombre_persona,
            rol_id=rol_comprador.id,
            activo=True
        )
        nuevo_comprador.set_password(password)
        db.session.add(nuevo_comprador)
        db.session.flush()
        obtener_o_crear_cliente_comprador(nuevo_comprador)
        db.session.commit()

        flash('¡Cuenta de COMPRADOR creada con éxito! Ya puedes iniciar sesión.')
        return redirect(url_for('login'))

    return render_template('registro_comprador.html')


@app.route('/logout')
@login_requerido
def logout():
    session.clear()
    flash('Sesión cerrada correctamente.')
    return redirect(url_for('login'))


# --- GESTIÓN DE USUARIOS Y ROLES (SOLO ADMIN) ---
@app.route('/usuarios', methods=['GET', 'POST'])
@roles_requeridos('ADMIN')
def gestionar_usuarios():
    roles = Rol.query.order_by(Rol.id.asc()).all()

    if request.method == 'POST':
        username = request.form['username'].strip()
        nombre_persona = request.form['nombre_persona'].strip()
        password = request.form['password']
        rol_id = int(request.form['rol_id'])

        if Usuario.query.filter_by(username=username).first():
            flash('Ese nombre de usuario ya existe. Elige otro.')
            return redirect(url_for('gestionar_usuarios'))

        nuevo_usuario = Usuario(
            username=username,
            nombre_persona=nombre_persona,
            rol_id=rol_id,
            activo=True
        )
        nuevo_usuario.set_password(password)
        db.session.add(nuevo_usuario)
        db.session.commit()

        flash(f'Usuario "{username}" creado con éxito.')
        return redirect(url_for('gestionar_usuarios'))

    usuarios = Usuario.query.order_by(Usuario.id.asc()).all()
    return render_template('usuarios.html', usuarios=usuarios, roles=roles)


@app.route('/usuarios/<int:id>/toggle-estado', methods=['POST'])
@roles_requeridos('ADMIN')
def toggle_estado_usuario(id):
    usuario = db.get_or_404(Usuario, id)
    if usuario.id == g.usuario.id:
        flash('No puedes desactivar tu propio usuario mientras tienes sesión abierta.')
        return redirect(url_for('gestionar_usuarios'))

    usuario.activo = not usuario.activo
    db.session.commit()
    estado_txt = 'activado' if usuario.activo else 'desactivado'
    flash(f'Usuario "{usuario.username}" {estado_txt}.')
    return redirect(url_for('gestionar_usuarios'))


# --- MENÚ PRINCIPAL (CATÁLOGO + GESTIÓN LATERAL) ---
@app.route('/')
@app.route('/catalogo')
@login_requerido
def home():
    categoria = request.args.get('categoria', '').strip()
    buscar = request.args.get('q', '').strip()

    query = Producto.query
    if categoria and categoria != 'Todos':
        query = query.filter_by(categoria=categoria)
    if buscar:
        query = query.filter(Producto.nombre.ilike(f'%{buscar}%'))

    productos = query.order_by(Producto.id.asc()).all()
    categorias = ['Todos', 'Semilla', 'Insecticida', 'Hidrosoluble', 'Herramientas']
    items_carrito, total_carrito, total_unidades = calcular_resumen_carrito()

    return render_template(
        'index.html',
        productos=productos,
        categorias=categorias,
        categoria_actual=categoria or 'Todos',
        buscar=buscar,
        items_carrito=items_carrito,
        total_carrito=total_carrito,
        total_unidades=total_unidades
    )


# --- CLIENTES (ADMIN y VENDEDOR) ---
@app.route('/registrar-cliente', methods=['GET', 'POST'])
@roles_requeridos('ADMIN', 'VENDEDOR')
def registrar_cliente():
    if request.method == 'POST':
        nombre = request.form['nombre']
        dui = request.form['dui']
        telefono = request.form['telefono']
        direccion = request.form['direccion']

        nuevo_cliente = Cliente(nombre=nombre, dui=dui, telefono=telefono, direccion=direccion)
        db.session.add(nuevo_cliente)
        db.session.commit()

        flash('¡Agricultor registrado con éxito en la base de datos!')
        return redirect(url_for('registrar_cliente'))

    return render_template('nuevo_cliente.html')


@app.route('/clientes')
@roles_requeridos('ADMIN', 'VENDEDOR')
def listar_clientes():
    clientes = Cliente.query.all()
    return render_template('listar_clientes.html', clientes=clientes)


@app.route('/editar-cliente/<int:id>', methods=['GET', 'POST'])
@roles_requeridos('ADMIN', 'VENDEDOR')
def editar_cliente(id):
    cliente = db.get_or_404(Cliente, id)
    if request.method == 'POST':
        cliente.nombre = request.form['nombre']
        cliente.dui = request.form['dui']
        cliente.telefono = request.form['telefono']
        cliente.direccion = request.form['direccion']
        db.session.commit()
        flash('¡Datos del agricultor actualizados con éxito!')
        return redirect(url_for('listar_clientes'))

    return render_template('editar_cliente.html', cliente=cliente)


@app.route('/eliminar-cliente/<int:id>', methods=['POST'])
@roles_requeridos('ADMIN')
def eliminar_cliente(id):
    cliente = db.get_or_404(Cliente, id)
    db.session.delete(cliente)
    db.session.commit()
    flash('¡Agricultor eliminado del sistema!')
    return redirect(url_for('listar_clientes'))


# --- CRÉDITOS (SOLO ADMIN) ---
@app.route('/registrar-credito', methods=['GET', 'POST'])
@roles_requeridos('ADMIN')
def registrar_credito():
    if request.method == 'POST':
        cliente_id = request.form['cliente_id']
        monto = float(request.form['monto'])

        nuevo_credito = Credito(
            monto=monto,
            saldo_pendiente=monto,
            estado='Activo',
            cliente_id=cliente_id
        )
        db.session.add(nuevo_credito)
        db.session.commit()

        flash('¡Crédito agrícola otorgado con éxito!')
        return redirect(url_for('registrar_credito'))

    lista_clientes = Cliente.query.all()
    return render_template('nuevo_credito.html', clientes=lista_clientes)


# --- RUTAS ---
@app.route('/registrar-ruta', methods=['GET', 'POST'])
@roles_requeridos('ADMIN', 'VENDEDOR')
def registrar_ruta():
    if request.method == 'POST':
        cliente_id = request.form['cliente_id']
        destino = request.form['destino']
        descripcion_carga = request.form['descripcion_carga']
        fecha_programada = request.form['fecha_programada']

        nueva_ruta = Ruta(
            destino=destino,
            descripcion_carga=descripcion_carga,
            fecha_programada=fecha_programada,
            estado='Programada',
            cliente_id=cliente_id
        )
        db.session.add(nueva_ruta)
        db.session.commit()

        flash('¡Ruta de entrega programada con éxito!')
        return redirect(url_for('registrar_ruta'))

    lista_clientes = Cliente.query.all()
    return render_template('nueva_ruta.html', clientes=lista_clientes)


@app.route('/rutas')
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def listar_rutas():
    if g.usuario.es_comprador:
        cliente = obtener_o_crear_cliente_comprador(g.usuario)
        db.session.commit()
        rutas = Ruta.query.filter_by(cliente_id=cliente.id).order_by(Ruta.id.desc()).all()
    else:
        rutas = Ruta.query.order_by(Ruta.id.desc()).all()
    return render_template('listar_rutas.html', rutas=rutas)


@app.route('/ver-ruta/<int:id>')
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def ver_ruta(id):
    ruta = db.get_or_404(Ruta, id)
    if g.usuario.es_comprador:
        cliente = obtener_o_crear_cliente_comprador(g.usuario)
        db.session.commit()
        if ruta.cliente_id != cliente.id:
            flash('Acceso denegado: solo puedes consultar tus propias rutas de entrega.')
            return redirect(url_for('listar_rutas'))
    url_maps = construir_url_maps(ruta.destino)
    return render_template('ver_ruta.html', ruta=ruta, url_maps=url_maps)


@app.route('/eliminar-ruta/<int:id>', methods=['POST'])
@roles_requeridos('ADMIN')
def eliminar_ruta(id):
    ruta = db.get_or_404(Ruta, id)
    db.session.delete(ruta)
    db.session.commit()
    flash('¡Ruta de entrega eliminada del sistema!')
    return redirect(url_for('listar_rutas'))


# --- CATÁLOGO (CREACIÓN Y EDICIÓN SOLO ADMIN) Y CARRITO ---
@app.route('/catalogo/nuevo-producto', methods=['POST'])
@roles_requeridos('ADMIN')
def crear_producto_catalogo():
    nombre = request.form['nombre'].strip()
    categoria = request.form['categoria'].strip()
    precio = float(request.form['precio'])
    stock = max(0, int(request.form.get('stock', 50)))

    if not nombre or precio <= 0:
        flash('Ingresa un nombre válido y un precio mayor a $0.00.')
        return redirect(url_for('home'))

    nombre_archivo = None
    archivo = request.files.get('imagen')
    if archivo and archivo.filename:
        if not archivo_imagen_permitido(archivo.filename):
            flash('Formato de imagen no válido. Usa PNG, JPG, JPEG o WEBP.')
            return redirect(url_for('home'))

        seguro = secure_filename(archivo.filename)
        marca_tiempo = datetime.now().strftime('%Y%m%d%H%M%S')
        nombre_archivo = f"{marca_tiempo}_{seguro}"
        archivo.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo))

    nuevo_prod = Producto(
        nombre=nombre,
        categoria=categoria,
        precio=round(precio, 2),
        stock=stock,
        imagen=nombre_archivo
    )
    db.session.add(nuevo_prod)
    db.session.commit()

    flash(f'Producto "{nombre}" agregado al catálogo.')
    return redirect(url_for('home'))


@app.route('/catalogo/editar-producto/<int:producto_id>', methods=['POST'])
@roles_requeridos('ADMIN')
def editar_producto_catalogo(producto_id):
    producto = db.get_or_404(Producto, producto_id)

    nombre = request.form.get('nombre', '').strip()
    categoria = request.form.get('categoria', '').strip()
    precio = float(request.form.get('precio', producto.precio))
    stock = max(0, int(request.form.get('stock', producto.stock)))

    if nombre:
        producto.nombre = nombre
    if categoria:
        producto.categoria = categoria
    if precio > 0:
        producto.precio = round(precio, 2)
    producto.stock = stock

    archivo = request.files.get('imagen')
    if archivo and archivo.filename:
        if not archivo_imagen_permitido(archivo.filename):
            flash('Formato de imagen no válido. Usa PNG, JPG, JPEG o WEBP.')
            return redirect(url_for('home'))

        seguro = secure_filename(archivo.filename)
        marca_tiempo = datetime.now().strftime('%Y%m%d%H%M%S')
        nombre_archivo = f"{marca_tiempo}_{seguro}"
        archivo.save(os.path.join(app.config['UPLOAD_FOLDER'], nombre_archivo))
        producto.imagen = nombre_archivo

    db.session.commit()
    flash(f'Producto "{producto.nombre}" actualizado.')
    return redirect(url_for('home'))


@app.route('/carrito/agregar/<int:producto_id>', methods=['POST'])
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def agregar_al_carrito(producto_id):
    producto = db.get_or_404(Producto, producto_id)
    cantidad = max(1, int(request.form.get('cantidad', 1)))

    carrito = obtener_carrito()
    clave = str(producto.id)
    carrito[clave] = carrito.get(clave, 0) + cantidad
    session['carrito'] = carrito
    session.modified = True

    flash(f'Agregado al carrito: {cantidad} x {producto.nombre}.')
    return redirect(request.referrer or url_for('home'))


@app.route('/carrito/actualizar/<int:producto_id>', methods=['POST'])
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def actualizar_carrito(producto_id):
    cantidad = int(request.form.get('cantidad', 1))
    carrito = obtener_carrito()
    clave = str(producto_id)

    if cantidad <= 0:
        carrito.pop(clave, None)
        flash('Producto eliminado del carrito.')
    else:
        carrito[clave] = cantidad
        flash('Cantidad actualizada en el carrito.')

    session['carrito'] = carrito
    session.modified = True
    return redirect(request.referrer or url_for('home'))


@app.route('/carrito/vaciar', methods=['POST'])
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def vaciar_carrito():
    session['carrito'] = {}
    session.modified = True
    flash('Carrito vaciado.')
    return redirect(request.referrer or url_for('home'))


# --- COMPRA EN LÍNEA CON TARJETA + ENVÍO A DOMICILIO + RUTA MAPS (COMPRADOR) ---
@app.route('/carrito/pagar-tarjeta', methods=['POST'])
@roles_requeridos('COMPRADOR')
def pagar_carrito_tarjeta():
    items_carrito, subtotal_carrito, total_unidades = calcular_resumen_carrito()
    if not items_carrito or subtotal_carrito <= 0:
        flash('Tu carrito está vacío.')
        return redirect(url_for('home'))

    titular = request.form.get('titular_tarjeta', '').strip()
    numero_raw = re.sub(r'\D', '', request.form.get('numero_tarjeta', ''))
    expiracion = request.form.get('expiracion_tarjeta', '').strip()
    cvv_raw = re.sub(r'\D', '', request.form.get('cvv_tarjeta', ''))

    zona_envio = request.form.get('zona_envio', 'Sonsonate Centro').strip()
    detalle_direccion = request.form.get('direccion_entrega', '').strip()
    telefono_contacto = request.form.get('telefono_contacto', '').strip()

    if len(titular) < 3:
        flash('Ingresa el nombre del titular de la tarjeta de crédito.')
        return redirect(url_for('home'))

    if len(numero_raw) < 13 or len(numero_raw) > 19:
        flash('Ingresa un número de tarjeta de crédito válido (13 a 19 dígitos).')
        return redirect(url_for('home'))

    if not re.match(r'^(0[1-9]|1[0-2])\/\d{2}$', expiracion):
        flash('Ingresa la fecha de expiración en formato MM/AA (Ej. 08/28).')
        return redirect(url_for('home'))

    if len(cvv_raw) not in (3, 4):
        flash('Ingresa un código de seguridad CVV válido (3 o 4 dígitos).')
        return redirect(url_for('home'))

    if not detalle_direccion:
        flash('Indica hasta dónde quieres que te lleven las cosas (dirección o punto de entrega).')
        return redirect(url_for('home'))

    for item in items_carrito:
        if item['cantidad'] > item['producto'].stock:
            flash(f"Stock insuficiente para {item['producto'].nombre} (disponible: {item['producto'].stock}).")
            return redirect(url_for('home'))

    for item in items_carrito:
        prod = item['producto']
        prod.stock = max(0, prod.stock - item['cantidad'])

    tarifa_envio = round(TARIFAS_ENVIO.get(zona_envio, 6.50), 2)
    total_con_envio = round(subtotal_carrito + tarifa_envio, 2)
    destino_completo = f"{detalle_direccion}, {zona_envio}, El Salvador"

    cliente = obtener_o_crear_cliente_comprador(
        g.usuario,
        telefono=telefono_contacto,
        direccion=destino_completo
    )

    ultimo_id = db.session.query(db.func.max(Factura.id)).scalar() or 0
    numero_factura = f"WEB-{datetime.now().year}-{ultimo_id + 1:04d}"
    ultimos4 = numero_raw[-4:]
    detalle_items = ', '.join([f"{i['cantidad']}x {i['producto'].nombre}" for i in items_carrito])
    concepto_pago = (
        f"[Tarjeta **** {ultimos4} · Envío ${tarifa_envio:.2f} a {zona_envio}] "
        f"{detalle_items}"
    )

    factura = Factura(
        numero_factura=numero_factura,
        fecha=datetime.now().strftime('%Y-%m-%d'),
        concepto=concepto_pago[:250],
        cantidad=total_unidades,
        precio_unitario=round(total_con_envio / total_unidades, 2),
        total=total_con_envio,
        cliente_id=cliente.id,
        credito_id=None
    )
    db.session.add(factura)

    ruta_entrega = Ruta(
        destino=destino_completo[:200],
        descripcion_carga=(
            f"Pedido {numero_factura}: {detalle_items}. "
            f"Origen: {ORIGEN_TIENDA}. Tarifa envío: ${tarifa_envio:.2f}. "
            f"Contacto: {telefono_contacto or 'N/A'}"
        ),
        fecha_programada=datetime.now().strftime('%Y-%m-%d'),
        estado='Programada',
        cliente_id=cliente.id
    )
    db.session.add(ruta_entrega)

    session['carrito'] = {}
    session.modified = True
    db.session.commit()

    flash(
        f'¡Pago con tarjeta **** {ultimos4} aprobado por ${total_con_envio:.2f} '
        f'(incluye envío ${tarifa_envio:.2f})! Factura {numero_factura} y ruta a {zona_envio} creadas.'
    )
    return redirect(url_for('listar_facturas'))


# --- FACTURACIÓN EN TIENDA FÍSICA (ADMIN y VENDEDOR) ---
@app.route('/nueva-factura', methods=['GET', 'POST'])
@roles_requeridos('ADMIN', 'VENDEDOR')
def nueva_factura():
    items_carrito, total_carrito, total_unidades = calcular_resumen_carrito()

    if request.method == 'POST':
        cliente_id = int(request.form['cliente_id'])
        concepto = request.form['concepto']
        cantidad = int(request.form['cantidad'])
        precio_unitario = float(request.form['precio_unitario'])
        total = round(float(request.form.get('total_manual') or (cantidad * precio_unitario)), 2)

        credito = Credito.query.filter_by(cliente_id=cliente_id, estado='Activo').first()
        if not credito:
            flash('Error: Este agricultor no tiene un crédito agrícola activo.')
            return redirect(url_for('nueva_factura'))

        if total > credito.saldo_pendiente:
            flash(f'Saldo insuficiente: El gasto (${total:.2f}) supera el saldo disponible del crédito (${credito.saldo_pendiente:.2f}).')
            return redirect(url_for('nueva_factura'))

        credito.saldo_pendiente = round(credito.saldo_pendiente - total, 2)
        if credito.saldo_pendiente == 0:
            credito.estado = 'Agotado'

        for item in items_carrito:
            prod = item['producto']
            prod.stock = max(0, prod.stock - item['cantidad'])

        ultimo_id = db.session.query(db.func.max(Factura.id)).scalar() or 0
        numero_factura = f"FAC-{datetime.now().year}-{ultimo_id + 1:04d}"

        factura = Factura(
            numero_factura=numero_factura,
            fecha=datetime.now().strftime('%Y-%m-%d'),
            concepto=concepto,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            total=total,
            cliente_id=cliente_id,
            credito_id=credito.id
        )
        db.session.add(factura)
        session['carrito'] = {}
        session.modified = True
        db.session.commit()

        flash(f'¡Factura {numero_factura} emitida por ${total:.2f}! Saldo restante: ${credito.saldo_pendiente:.2f}')
        return redirect(url_for('ver_facturas_cliente', cliente_id=cliente_id))

    clientes = Cliente.query.all()
    saldos_por_cliente = {}
    for c in clientes:
        cred_activo = Credito.query.filter_by(cliente_id=c.id, estado='Activo').first()
        saldos_por_cliente[str(c.id)] = round(cred_activo.saldo_pendiente, 2) if cred_activo else 0.0

    concepto_sugerido = ', '.join([f"{i['cantidad']}x {i['producto'].nombre}" for i in items_carrito])

    return render_template(
        'nueva_factura.html',
        clientes=clientes,
        items_carrito=items_carrito,
        total_carrito=total_carrito,
        total_unidades=total_unidades,
        concepto_sugerido=concepto_sugerido,
        saldos_por_cliente=saldos_por_cliente
    )


@app.route('/cliente/<int:cliente_id>/facturas')
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def ver_facturas_cliente(cliente_id):
    cliente = db.get_or_404(Cliente, cliente_id)
    if g.usuario.es_comprador:
        propio = obtener_o_crear_cliente_comprador(g.usuario)
        db.session.commit()
        if cliente.id != propio.id:
            flash('Acceso denegado: solo puedes ver tus propias facturas.')
            return redirect(url_for('listar_facturas'))

    facturas = Factura.query.filter_by(cliente_id=cliente_id).order_by(Factura.id.desc()).all()
    creditos = Credito.query.filter_by(cliente_id=cliente_id).all()

    total_otorgado = sum(c.monto for c in creditos)
    total_gastado = sum(f.total for f in facturas)
    saldo_disponible = sum(c.saldo_pendiente for c in creditos)

    return render_template(
        'facturas_cliente.html',
        cliente=cliente,
        facturas=facturas,
        total_otorgado=total_otorgado,
        total_gastado=total_gastado,
        saldo_disponible=saldo_disponible
    )


@app.route('/facturas')
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def listar_facturas():
    if g.usuario.es_comprador:
        cliente = obtener_o_crear_cliente_comprador(g.usuario)
        db.session.commit()
        facturas = Factura.query.filter_by(cliente_id=cliente.id).order_by(Factura.id.desc()).all()
    else:
        facturas = Factura.query.order_by(Factura.id.desc()).all()
    return render_template('listar_facturas.html', facturas=facturas)


@app.route('/factura/<int:id>/vista')
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def vista_factura(id):
    factura = db.get_or_404(Factura, id)
    if g.usuario.es_comprador:
        cliente = obtener_o_crear_cliente_comprador(g.usuario)
        db.session.commit()
        if factura.cliente_id != cliente.id:
            flash('Acceso denegado: solo puedes consultar tus propias facturas.')
            return redirect(url_for('listar_facturas'))
    credito = db.session.get(Credito, factura.credito_id) if factura.credito_id else None
    ruta = Ruta.query.filter_by(cliente_id=factura.cliente_id).order_by(Ruta.id.desc()).first()
    url_maps = construir_url_maps(ruta.destino if ruta else ORIGEN_TIENDA)
    return render_template(
        'factura_pdf.html',
        factura=factura,
        credito=credito,
        ruta=ruta,
        url_maps=url_maps,
        modo_pdf=False
    )


@app.route('/factura/<int:id>/pdf')
@roles_requeridos('ADMIN', 'VENDEDOR', 'COMPRADOR')
def descargar_factura_pdf(id):
    factura = db.get_or_404(Factura, id)
    if g.usuario.es_comprador:
        cliente = obtener_o_crear_cliente_comprador(g.usuario)
        db.session.commit()
        if factura.cliente_id != cliente.id:
            flash('Acceso denegado: solo puedes descargar tus propias facturas.')
            return redirect(url_for('listar_facturas'))
    credito = db.session.get(Credito, factura.credito_id) if factura.credito_id else None
    ruta = Ruta.query.filter_by(cliente_id=factura.cliente_id).order_by(Ruta.id.desc()).first()
    url_maps = construir_url_maps(ruta.destino if ruta else ORIGEN_TIENDA)
    html = render_template(
        'factura_pdf.html',
        factura=factura,
        credito=credito,
        ruta=ruta,
        url_maps=url_maps,
        modo_pdf=True
    )

    pdf_buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf_buffer)

    if pisa_status.err:
        return "Error al generar el documento PDF", 500

    response = make_response(pdf_buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    accion = request.args.get('accion', 'attachment')
    response.headers['Content-Disposition'] = f'{accion}; filename={factura.numero_factura}.pdf'
    return response


with app.app_context():
    inicializar_datos_base()

if __name__ == '__main__':
    app.run(debug=True)