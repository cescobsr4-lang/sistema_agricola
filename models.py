from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class Rol(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(30), unique=True, nullable=False)
    descripcion = db.Column(db.String(150))

    usuarios = db.relationship('Usuario', backref='rol', lazy=True)


class Usuario(db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    nombre_persona = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    activo = db.Column(db.Boolean, default=True, nullable=False)
    rol_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def es_admin(self):
        return self.rol and self.rol.nombre.upper() == 'ADMIN'

    @property
    def es_vendedor(self):
        return self.rol and self.rol.nombre.upper() == 'VENDEDOR'

    @property
    def es_comprador(self):
        return self.rol and self.rol.nombre.upper() == 'COMPRADOR'


class Cliente(db.Model):
    __tablename__ = 'clientes'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    dui = db.Column(db.String(15), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    direccion = db.Column(db.String(200))

    creditos = db.relationship('Credito', backref='cliente', cascade='all, delete-orphan', lazy=True)
    rutas = db.relationship('Ruta', backref='cliente', cascade='all, delete-orphan', lazy=True)
    facturas = db.relationship('Factura', backref='cliente', cascade='all, delete-orphan', lazy=True)


class Credito(db.Model):
    __tablename__ = 'creditos'
    id = db.Column(db.Integer, primary_key=True)
    monto = db.Column(db.Float, nullable=False)
    saldo_pendiente = db.Column(db.Float, nullable=False)
    estado = db.Column(db.String(20), default='Activo')
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)


class Ruta(db.Model):
    __tablename__ = 'rutas'
    id = db.Column(db.Integer, primary_key=True)
    destino = db.Column(db.String(200), nullable=False)
    descripcion_carga = db.Column(db.Text, nullable=False)
    fecha_programada = db.Column(db.String(20), nullable=False)
    estado = db.Column(db.String(20), default='Programada')
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)


class Factura(db.Model):
    __tablename__ = 'facturas'
    id = db.Column(db.Integer, primary_key=True)
    numero_factura = db.Column(db.String(30), unique=True, nullable=False)
    fecha = db.Column(db.String(20), default=lambda: datetime.now().strftime('%Y-%m-%d'))
    concepto = db.Column(db.String(250), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    precio_unitario = db.Column(db.Float, nullable=False)
    total = db.Column(db.Float, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id'), nullable=False)
    credito_id = db.Column(db.Integer, db.ForeignKey('creditos.id'), nullable=True)


class Producto(db.Model):
    __tablename__ = 'productos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(50), nullable=False)
    precio = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=100)
    imagen = db.Column(db.String(200), nullable=True)