import os
import uuid
import re
import json
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS

# --- CONFIGURAÇÃO DE ALTA PERFORMANCE V8.3 ---
app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "elim-core-quantum-2026-v8-ultra"),
    SQLALCHEMY_DATABASE_URI="sqlite:///portal_elim_v8.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    JSON_AS_ASCII=False,
    MAX_CONTENT_LENGTH=100 * 1024 * 1024, # 100MB
    UPLOAD_FOLDER=UPLOAD_FOLDER
)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Sessão expirada ou acesso restrito."
login_manager.login_message_category = "warning"
CORS(app)

# --- DATABASE MODELS ---

class Unidade(db.Model):
    __tablename__ = "unidades"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False, unique=True)
    cidade = db.Column(db.String(100))
    usuarios = db.relationship("User", backref="unidade", lazy='dynamic')

class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="aluno", nullable=False) 
    xp = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    is_approved = db.Column(db.Boolean, default=False)
    unidade_id = db.Column(db.Integer, db.ForeignKey("unidades.id"))
    
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    logs = db.relationship('LogAtividade', backref='owner', cascade="all, delete-orphan")
    progresso = db.relationship('ProgressoAula', backref='estudante', lazy='dynamic', cascade="all, delete-orphan")
    notificacoes = db.relationship('Notification', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Aula(db.Model):
    __tablename__ = "aulas"
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True)
    descricao = db.Column(db.Text)
    url_video = db.Column(db.String(500)) 
    categoria = db.Column(db.String(100), index=True)
    minutos_estimados = db.Column(db.Integer, default=0)
    xp_recompensa = db.Column(db.Integer, default=100)
    quiz_data = db.Column(db.JSON) 
    status = db.Column(db.String(20), default="publicado")
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    criado_por = db.Column(db.Integer, db.ForeignKey('users.id'))

class ProgressoAula(db.Model):
    __tablename__ = "progresso_aulas"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    aula_id = db.Column(db.Integer, db.ForeignKey('aulas.id'))
    concluido = db.Column(db.Boolean, default=False)
    nota_quiz = db.Column(db.Float, nullable=True)
    data_conclusao = db.Column(db.DateTime, default=datetime.utcnow)

class LogAtividade(db.Model):
    __tablename__ = "logs_atividades"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    acao = db.Column(db.String(255))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    mensagem = db.Column(db.String(255))
    lida = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- UTILITÁRIOS ---

def registrar_log(acao):
    if current_user and current_user.is_authenticated:
        log = LogAtividade(
            user_id=current_user.id, 
            acao=acao, 
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )
        db.session.add(log)
        db.session.commit()

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                if request.is_json:
                    return jsonify({"success": False, "error": "Acesso Negado"}), 403
                flash("Área restrita. Você não possui as permissões necessárias.", "danger")
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def extrair_id_youtube(url):
    if not url: return ""
    regex = r'(?:v=|\/|be\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(regex, url)
    return match.group(1) if match else url

# --- ROTAS PRINCIPAIS ---

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
@login_required
def dashboard():
    stats = {
        "aulas_count": db.session.query(Aula).count(),
        "meu_progresso": current_user.progresso.filter_by(concluido=True).count(),
        "xp": current_user.xp,
        "atividades": LogAtividade.query.filter_by(user_id=current_user.id).order_by(LogAtividade.timestamp.desc()).limit(8).all()
    }
    return render_template("home.html", **stats)

@app.route("/aulas")
@login_required
def lista_aulas():
    categoria = request.args.get('cat')
    query = Aula.query.filter_by(status="publicado")
    if categoria:
        query = query.filter_by(categoria=categoria)
    aulas = query.order_by(Aula.data_criacao.desc()).all()
    return render_template("aulas_lista.html", aulas=aulas)

@app.route("/aula/<slug>")
@login_required
def ver_aula(slug):
    aula = Aula.query.filter_by(slug=slug).first_or_404()
    progresso = ProgressoAula.query.filter_by(user_id=current_user.id, aula_id=aula.id).first()
    return render_template("aula.html", aula=aula, progresso=progresso)

@app.route("/aula/<slug>/desafio")
@login_required
def ver_desafio(slug):
    aula = Aula.query.filter_by(slug=slug).first_or_404()
    if not aula.quiz_data:
        flash("Esta aula não possui um desafio disponível.", "info")
        return redirect(url_for('ver_aula', slug=slug))
    return render_template("desafio.html", aula=aula)

# --- SISTEMA DE PROGRESSO E XP ---

@app.route("/api/aulas/concluir", methods=['POST'])
@login_required
def concluir_aula():
    data = request.get_json()
    aula_id = data.get('aula_id')
    nota = data.get('nota', 0)
    
    aula = db.session.get(Aula, aula_id)
    if not aula:
        return jsonify({"success": False, "message": "Aula não encontrada"}), 404

    progresso = ProgressoAula.query.filter_by(user_id=current_user.id, aula_id=aula.id).first()
    
    if not progresso:
        novo_progresso = ProgressoAula(
            user_id=current_user.id, 
            aula_id=aula.id, 
            concluido=True, 
            nota_quiz=nota
        )
        current_user.xp += aula.xp_recompensa
        db.session.add(novo_progresso)
        msg = f"Concluiu a aula e desafio: {aula.titulo}"
    else:
        progresso.nota_quiz = max(progresso.nota_quiz or 0, nota)
        msg = f"Refez o desafio da aula: {aula.titulo}"

    db.session.commit()
    registrar_log(msg)
    return jsonify({"success": True, "new_xp": current_user.xp})

# --- SISTEMA DE GESTÃO DE CONTEÚDO (CMS) ---

@app.route("/upload")
@role_required('admin', 'professor')
def upload():
    return render_template("upload.html")

@app.route("/api/aulas/cadastrar", methods=['POST'])
@role_required('admin', 'professor')
def api_cadastrar_aula():
    data = request.get_json()
    if not data or not data.get('nome'):
        return jsonify({"success": False, "message": "O título da aula é obrigatório"}), 400

    try:
        base_slug = data.get('nome').lower().strip()
        base_slug = re.sub(r'\s+', '-', base_slug)
        base_slug = re.sub(r'[^a-z0-9-]', '', base_slug)
        slug = f"{base_slug}-{str(uuid.uuid4())[:5]}"
        
        video_id = extrair_id_youtube(data.get('url_video'))
        
        nova_aula = Aula(
            titulo=data.get('nome'),
            slug=slug,
            descricao=data.get('descricao'),
            url_video=video_id,
            categoria=data.get('categoria', 'Geral'),
            minutos_estimados=int(data.get('tempo', 0)),
            xp_recompensa=int(data.get('xp', 100)),
            quiz_data=data.get('quiz'),
            criado_por=current_user.id
        )
        
        db.session.add(nova_aula)
        db.session.commit()
        registrar_log(f"Publicou nova aula: {nova_aula.titulo}")
        
        return jsonify({"success": True, "message": "Aula publicada!", "redirect": "/aulas"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Erro interno: {str(e)}"}), 500

# --- ADMINISTRAÇÃO ---

@app.route("/admin/usuarios")
@role_required('admin')
def gerenciar_usuarios():
    users = User.query.all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/aprovacoes")
@role_required('admin')
def lista_aprovacoes():
    pedidos = User.query.filter_by(is_approved=False).order_by(User.created_at.desc()).all()
    return render_template("aceitarpedidos.html", pedidos=pedidos)

@app.route("/api/admin/aprovar/<int:user_id>", methods=['POST'])
@role_required('admin')
def api_aprovar_usuario(user_id):
    user = db.get_or_404(User, user_id)
    try:
        user.is_approved = True
        notif = Notification(user_id=user.id, mensagem="Parabéns! Sua conta foi aprovada.")
        db.session.add(notif)
        db.session.commit()
        registrar_log(f"Aprovou usuário: {user.email}")
        return jsonify({"success": True, "message": "Usuário aprovado com sucesso."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# --- AUTENTICAÇÃO ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        user = User.query.filter_by(email=data.get('email', '').lower()).first()
        
        if user and user.check_password(data.get('password')):
            if not user.is_approved:
                return jsonify({"success": False, "error": "Sua conta ainda não foi aprovada pelo administrador."}), 401
            
            login_user(user, remember=True)
            user.last_login = datetime.utcnow()
            db.session.commit()
            registrar_log("Login no sistema")
            return jsonify({"success": True, "redirect": url_for('dashboard')}) if request.is_json else redirect(url_for('dashboard'))
        
        return jsonify({"success": False, "error": "E-mail ou senha incorretos."}), 401
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    unidades = Unidade.query.all()
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        email = data.get('email', '').lower()
        if User.query.filter_by(email=email).first():
            return jsonify({"success": False, "error": "Este e-mail já está em uso."}), 409
        
        novo_user = User(name=data.get('name'), email=email, unidade_id=data.get('unidade_id'), role="aluno")
        novo_user.set_password(data.get('password'))
        db.session.add(novo_user)
        db.session.commit()
        return jsonify({"success": True, "message": "Cadastro realizado! Aguarde a aprovação do administrador."})
    return render_template('register.html', unidades=unidades)

@app.route("/logout")
@login_required
def logout():
    registrar_log("Saiu do sistema")
    logout_user()
    return redirect(url_for('login'))

# --- PERFIL ---

@app.route("/perfil")
@login_required
def perfil():
    unidades = Unidade.query.all()
    return render_template("perfil.html", user=current_user, unidades=unidades)

@app.route("/api/perfil/atualizar", methods=['POST'])
@login_required
def api_atualizar_perfil():
    data = request.get_json()
    try:
        if 'email' in data or 'new_password' in data:
            if not current_user.check_password(data.get('current_password')):
                return jsonify({"success": False, "message": "Senha atual incorreta."}), 401
        
        if 'name' in data: current_user.name = data.get('name')
        if 'email' in data: current_user.email = data.get('email').lower()
        if 'unidade_id' in data: current_user.unidade_id = data.get('unidade_id')
        if 'new_password' in data: current_user.set_password(data.get('new_password'))
        
        db.session.commit()
        registrar_log("Atualizou dados do perfil")
        return jsonify({"success": True, "message": "Perfil atualizado com sucesso!"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

# --- SETUP INICIAL ---

def setup_initial_data():
    with app.app_context():
        db.create_all()
        if not db.session.query(Unidade).first():
            db.session.add(Unidade(nome="Campus Central", cidade="Luanda"))
            db.session.commit()
        if not User.query.filter_by(role="admin").first():
            admin = User(name="Gestor Quantum", email="master@elim.edu", role="admin", is_approved=True, unidade_id=1)
            admin.set_password("elim@2026")
            db.session.add(admin)
            db.session.commit()
            print(">>> [SISTEMA] Admin Master configurado: master@elim.edu / elim@2026")

if __name__ == "__main__":
    setup_initial_data()
    app.run(debug=True, host="0.0.0.0", port=5000)