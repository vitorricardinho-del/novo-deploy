from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_moment import Moment 
from datetime import datetime, timedelta, timezone
import os, time
from werkzeug.utils import secure_filename
from functools import wraps
from PIL import Image
from werkzeug.security import check_password_hash
from sqlalchemy import func

app = Flask(__name__)
app.config['SECRET_KEY'] = 'uma-chave-muito-segura'

# --- CONFIGURAÇÃO ---
app.config['BABEL_DEFAULT_LOCALE'] = 'pt_br'
moment = Moment(app)
fuso_ivinhema = timezone(timedelta(hours=-4))

# --- ADMIN ---
HASH_NOME = "scrypt:32768:8:1$0xB1zv3iVa46Cg6C$868d6addcff26950eace72985b1ff46081b4c7dfe37ee8aa38a6b0f5414140317b64ee5c128d624fe2a16e1bb72fab592e57c0c3ed989be4d21770fa559a42e2" 
HASH_SENHA = "scrypt:32768:8:1$7TMwbLFwWdtt1xIv$22f775be96a6a22227b4c64d30f5e7b17c0805c028e657702ea8a28cf85ff8a043b06d5dbe89902780c0845f7f8dae1b82d77a69953b13b64be3f82042ccb7e7"

def precisa_de_senha(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not (check_password_hash(HASH_NOME, auth.username) and check_password_hash(HASH_SENHA, auth.password)):
            return Response('Acesso negado!', 401, {'WWW-Authenticate': 'Basic realm="Login"'})
        return f(*args, **kwargs)
    return decorated

# --- BANCO DE DADOS ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'uploads')
app.config['IMAGENS_SISTEMA'] = os.path.join(BASE_DIR, 'static') 
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'mural.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- MODELOS ---
class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    pedidos = db.relationship('Pedido', backref='autor', lazy=True)

class Pedido(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(100), nullable=False)
    categoria = db.Column(db.String(50))
    descricao = db.Column(db.Text)
    whatsapp = db.Column(db.String(20))
    local = db.Column(db.String(100))
    foto = db.Column(db.String(200), default='sem-foto.jpg')
    foto2 = db.Column(db.String(200), default='') 
    foto3 = db.Column(db.String(200), default='')
    data_criacao = db.Column(db.DateTime, default=lambda: datetime.now(fuso_ivinhema)) 
    plano = db.Column(db.Integer, default=0) 
    is_premium = db.Column(db.Boolean, default=False)
    preco = db.Column(db.Numeric(10, 2), nullable=True)     
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'))
    acessos = db.Column(db.Integer, default=0)
    denuncias = db.Column(db.Integer, default=0)
    verificado = db.Column(db.Boolean, default=False)

class VendaEstatistica(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(50))
    data_venda = db.Column(db.DateTime, default=lambda: datetime.now(fuso_ivinhema))

# --- LIMPEZA ---
def limpar_expirados():
    hoje = datetime.now(fuso_ivinhema)
    limite_gratis = hoje - timedelta(days=7)
    limite_prata = hoje - timedelta(days=15)
    limite_ouro = hoje - timedelta(days=30)
    vencidos = Pedido.query.filter(
        ((Pedido.plano == 2) & (Pedido.data_criacao < limite_ouro)) |
        ((Pedido.plano == 1) & (Pedido.data_criacao < limite_prata)) |
        ((Pedido.plano == 0) & (Pedido.data_criacao < limite_gratis))
    ).all()
    for p in vencidos:
        for f in [p.foto, p.foto2, p.foto3]:
            if f and f != 'sem-foto.jpg':
                caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
                if os.path.exists(caminho): os.remove(caminho)
        db.session.delete(p)
    db.session.commit()

with app.app_context():
    db.create_all()

login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

# --- ROTAS ---

@app.route('/')
def exibir_mural():
    limpar_expirados()
    termo = request.args.get('q', '').strip()
    cat = request.args.get('categoria', '').strip() 
    query = Pedido.query.filter(Pedido.is_premium == True)
    if termo: 
        query = query.filter((Pedido.titulo.ilike(f'%{termo}%')) | (Pedido.categoria.ilike(f'%{termo}%')))
    if cat: 
        query = query.filter(Pedido.categoria == cat)
    pedidos = query.order_by(Pedido.plano.desc(), func.random()).all()
    return render_template('mural.html', pedidos=pedidos, busca_ativa=termo, cat_ativa=cat)

@app.route('/cadastrar')
@login_required
def pagina_cadastro():
    return render_template('cadastro.html')

@app.route('/salvar_pedido', methods=['POST'])
@login_required
def salvar_pedido():
    PROIBIDAS = ['caralho', 'porra', 'merda', 'puta', 'vigarista', 'golpe', 'urubu do pix', 'ladrão', 'admin', 'lula', 'Bolsonaro']
    titulo = request.form.get('titulo', '').lower()
    desc = request.form.get('descricao', '').lower()
    for p in PROIBIDAS:
        if p in titulo or p in desc:
            flash(f"⚠️ O termo '{p}' não é permitido.")
            return redirect(url_for('pagina_cadastro'))

    zap_bruto = request.form.get('whatsapp', '')
    zap_limpo = "".join(filter(str.isdigit, zap_bruto))
    valor_in = request.form.get('preco', '').strip()
    try:
        limpo = valor_in.replace('R$', '').replace('\xa0', '').replace('.', '').replace(',', '.').strip()
        preco_f = float(limpo) if limpo else 0.0
    except: preco_f = 0.0

    nomes = ['sem-foto.jpg', '', '']
    campos = ['foto', 'foto2', 'foto3']
    
    for i, campo in enumerate(campos):
        if campo in request.files:
            arq = request.files[campo]
            if arq.filename != '':
                ext = os.path.splitext(arq.filename)[1].lower()
                nome = secure_filename(f"foto_{int(time.time())}_{i+1}{ext}")
                caminho = os.path.join(app.config['UPLOAD_FOLDER'], nome)
                img = Image.open(arq)
                if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                img.save(caminho, optimize=True, quality=85)
                nomes[i] = nome

    try:
        plano = int(request.form.get('plano', 0))
        novo = Pedido(
            titulo=request.form.get('titulo'),
            categoria=request.form.get('categoria'),
            descricao=request.form.get('descricao'),
            whatsapp=zap_limpo,
            local=request.form.get('local'),
            foto=nomes[0], foto2=nomes[1], foto3=nomes[2],
            data_criacao=datetime.now(fuso_ivinhema),
            plano=plano, 
            is_premium=(True if plano == 0 else False),
            preco=preco_f, 
            usuario_id=current_user.id
        )
        db.session.add(novo)
        db.session.commit()
        return redirect(url_for('exibir_mural'))
    except Exception as e:
        db.session.rollback()
        flash("Erro ao salvar o anúncio.")
        return redirect(url_for('pagina_cadastro'))

@app.route('/editar_pedido/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_pedido(id):
    pedido = Pedido.query.get_or_404(id)
    if pedido.usuario_id != current_user.id:
        return redirect(url_for('exibir_mural'))
    if request.method == 'POST':
        pedido.titulo = request.form.get('titulo')
        pedido.categoria = request.form.get('categoria')
        pedido.descricao = request.form.get('descricao')
        pedido.local = request.form.get('local')
        db.session.commit()
        return redirect(url_for('exibir_mural'))
    return render_template('cadastro.html', pedido_edit=pedido)

@app.route('/denunciar_anuncio/<int:id>')
def denunciar_anuncio(id):
    p = Pedido.query.get_or_404(id)
    p.denuncias = (p.denuncias or 0) + 1
    db.session.commit()
    return jsonify({"status": "sucesso"})

@app.route('/contar_clique_imagem/<int:id>')
def contar_clique_imagem(id):
    p = Pedido.query.get_or_404(id)
    p.acessos = (p.acessos or 0) + 1
    db.session.commit()
    return jsonify({"status": "sucesso"})

@app.route('/registrar_venda/<string:categoria>')
def registrar_venda(categoria):
    try:
        nova_venda = VendaEstatistica(categoria=categoria)
        db.session.add(nova_venda)
        db.session.commit()
        return jsonify({"status": "sucesso"})
    except:
        return jsonify({"status": "erro"}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Usuario.query.filter_by(email=request.form.get('email').lower().strip()).first()
        if user and user.senha == request.form.get('senha'):
            login_user(user)
            return redirect(url_for('exibir_mural'))
    return render_template('login.html')

@app.route('/cadastro_usuario', methods=['GET', 'POST'])
def cadastro_usuario():
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').lower().strip()
        senha = request.form.get('senha')
        try:
            novo_usuario = Usuario(nome=nome, email=email, senha=senha)
            db.session.add(novo_usuario)
            db.session.commit()
            return redirect(url_for('login'))
        except:
            return redirect(url_for('cadastro_usuario'))
    return render_template('cadastro_usuario.html')

@app.route('/admin_mural')
@precisa_de_senha
def admin_mural():
    limpar_expirados()
    todos = Pedido.query.order_by(Pedido.id.desc()).all()
    
    # --- ESTATÍSTICAS DE VENDA ---
    vendas_lista = VendaEstatistica.query.all()
    total_vendas_realizadas = len(vendas_lista)
    stats_categorias = db.session.query(
        VendaEstatistica.categoria, 
        func.count(VendaEstatistica.id)
    ).group_by(VendaEstatistica.categoria).all()

    # --- RANKING DE ACESSOS ---
    mais_acessados = Pedido.query.order_by(Pedido.acessos.desc()).limit(5).all()
    top_1 = mais_acessados[0] if mais_acessados else None

    faturamento = sum(15 if p.plano==2 else 5 for p in todos if p.is_premium and p.plano > 0)
    total_den = sum(1 for p in todos if (p.denuncias or 0) > 0)
    
    return render_template('admin.html', 
                        pedidos=todos, 
                        faturamento=faturamento, 
                        total_denuncias=total_den, 
                        total_vendas=total_vendas_realizadas,
                        stats_categorias=stats_categorias, 
                        mais_acessados=mais_acessados,
                        top_1=top_1,
                        ultimos=todos[:5], 
                        pendentes=sum(1 for p in todos if not p.is_premium and p.plano > 0))

@app.route('/tornar_premium/<int:id>')
@precisa_de_senha
def tornar_premium(id):
    p = Pedido.query.get_or_404(id)
    p.is_premium = not p.is_premium
    db.session.commit()
    return redirect(url_for('admin_mural'))

@app.route('/limpar_denuncias/<int:id>')
@precisa_de_senha
def limpar_denuncias(id):
    p = Pedido.query.get_or_404(id)
    p.denuncias = 0  
    p.verificado = True
    db.session.commit()
    return redirect(url_for('admin_mural'))

@app.route('/excluir_pedido/<int:id>')
@login_required
def excluir_pedido(id):
    p = Pedido.query.get_or_404(id)
    for f in [p.foto, p.foto2, p.foto3]:
        if f and f != 'sem-foto.jpg' and f != '':
            caminho = os.path.join(app.config['UPLOAD_FOLDER'], f)
            if os.path.exists(caminho): os.remove(caminho)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for('exibir_mural'))

@app.route('/zerar_estatisticas')
@precisa_de_senha
def zerar_estatisticas():
    VendaEstatistica.query.delete()
    db.session.commit()
    return redirect(url_for('admin_mural'))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('exibir_mural'))

if __name__ == '__main__':
    app.run(debug=True)