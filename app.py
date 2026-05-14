from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
import hashlib
import secrets
import os
import requests
import datetime
from urllib.parse import urlencode

TWITCH_CLIENT_ID = "115y6026m2autr03fc31v8mijd94pb"
TWITCH_CLIENT_SECRET = "e4wdchj9wfhc9et1veal10zd8axgw6"
TWITCH_REDIRECT_URI = "http://127.0.0.1:5555/twitch/callback"

app = Flask(__name__)
app.config['SECRET_KEY'] = 'ваш-секретный-ключ-12345'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    salt = db.Column(db.String(100), nullable=False)
    downloads_count = db.Column(db.Integer, default=0)
    is_beta_tester = db.Column(db.Boolean, default=False)
    twitch_username = db.Column(db.String(80), nullable=True)
    twitch_subscribed = db.Column(db.Boolean, default=False)

def hashing(password):
    salt = secrets.token_hex(16)
    combo = password + salt
    hashs = hashlib.sha256(combo.encode()).hexdigest()
    return hashs, salt

def verify(password, st_hashs, salt):
    combo = password + salt
    hashs = hashlib.sha256(combo.encode()).hexdigest()
    return hashs == st_hashs

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        un = request.form["username"]
        email = request.form["email"]
        pas = request.form["password"]
        pas2 = request.form["confirm_password"]

        if pas != pas2:
            flash('Пароли не совпадают!', 'danger')
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email уже зарегистрирован!', 'danger')
            return redirect(url_for('register'))
        
        existing_username = User.query.filter_by(username=un).first()
        if existing_username:
            flash('Имя пользователя уже занято!', 'danger')
            return redirect(url_for('register'))
        
        hashs, salt = hashing(pas)

        new_user = User(username=un, email=email, password_hash=hashs, salt=salt)
        
        db.session.add(new_user)
        db.session.commit()

        flash(f"{un}, Успех!", 'success')
        send_discord_notification(
            "Новый участник!", 
            f"**{un}** присоединился к Fire Work Studio!\nEmail: {email}",
            color=0x1e6f3f
        )

        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        pas = request.form['password']

        user = User.query.filter_by(email=email).first()

        if user and verify(pas, user.password_hash, user.salt):
            session['user_id'] = user.id
            session['username'] = user.username
            session['email'] = user.email
            return redirect(url_for('profile'))
        else:
            flash('Неверный email или пароль!', 'danger')
        
    return render_template('login.html')

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в аккаунт', 'warning')
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    return render_template('profile.html', user=user)

@app.route('/download/<game_name>')
def download_game(game_name):
    if 'user_id' not in session:
        flash('Войдите в аккаунт', 'warning')
        return redirect(url_for('login'))
    
    if game_name == 'shift325_demo':
        user = db.session.get(User, session['user_id'])
        if not user.twitch_subscribed:
            flash('Для скачивания SHIFT 325 нужно подписаться на Twitch-канал!', 'warning')
            return redirect(url_for('twitch_login', pending='shift325_demo'))
    
    game_files = {
        'limbo_demo': 'limbo_demo.zip',
        'greatness_path': 'greatness_path.zip',
        'shift325_demo': 'shift325_demo.zip',
    }
    
    if game_name not in game_files:
        flash('Игра не найдена!', 'danger')
        return redirect(url_for('profile'))
    
    file_path = os.path.join('downloads', game_files[game_name])
    
    if not os.path.exists(file_path):
        flash('Файл игры временно недоступен', 'danger')
        return redirect(url_for('profile'))
    
    user = db.session.get(User, session['user_id'])
    user.downloads_count += 1
    db.session.commit()
    
    return send_file(file_path, as_attachment=True, download_name=game_files[game_name])

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из аккаунта', 'info')
    return redirect(url_for('home'))

@app.route('/team')
def team():
    return render_template('team.html')

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1504532587211915277/L-vTag61gi9ubpxULFnsgrJ-xa_5dpxEKPyZJqz2jOve0U6A08AJetqZwrBmyMpv65JS"

def send_discord_notification(title, description, color=0x6f6f92):
    data = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color, 
            "footer": {"text": "Fire Work Studio"},
            "timestamp": datetime.datetime.now().isoformat()
        }]
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=data)
        response.raise_for_status()
    except Exception as e:
        print(f"Ошибка отправки в Discord: {e}")

@app.route('/twitch/login')
def twitch_login():
    pending = request.args.get('pending', '')
    if pending:
        session['pending_download'] = pending
    
    params = {
        'client_id': TWITCH_CLIENT_ID,
        'redirect_uri': TWITCH_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'user:read:subscriptions user:read:email',
        'force_verify': 'true'
    }
    return redirect(f"https://id.twitch.tv/oauth2/authorize?{urlencode(params)}")

@app.route('/twitch/callback')
def twitch_callback():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в аккаунт', 'warning')
        return redirect(url_for('login'))
    
    code = request.args.get('code')
    if not code:
        flash('Ошибка авторизации', 'danger')
        return redirect(url_for('profile'))
    
    token_url = "https://id.twitch.tv/oauth2/token"
    data = {
        'client_id': TWITCH_CLIENT_ID,
        'client_secret': TWITCH_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': TWITCH_REDIRECT_URI
    }
    
    resp = requests.post(token_url, data=data)
    token_data = resp.json()
    
    if 'access_token' not in token_data:
        flash('Ошибка получения токена', 'danger')
        return redirect(url_for('profile'))
    
    access_token = token_data['access_token']
    headers = {'Authorization': f'Bearer {access_token}', 'Client-Id': TWITCH_CLIENT_ID}
    user_resp = requests.get('https://api.twitch.tv/helix/users', headers=headers)
    user_data = user_resp.json()
    
    if user_data.get('data'):
        twitch_name = user_data['data'][0]['login']
        user = db.session.get(User, session['user_id'])
        user.twitch_username = twitch_name
        db.session.commit()
        flash(f'Twitch аккаунт @{twitch_name} привязан!', 'success')
        
        pending = session.pop('pending_download', None)
        if pending == 'shift325_demo':
            return redirect(url_for('check_subscription'))
    
    return redirect(url_for('profile'))

@app.route('/check-subscription')
def check_subscription():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в аккаунт', 'warning')
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    
    if not user.twitch_username:
        flash('Сначала привяжите Twitch аккаунт', 'warning')
        return redirect(url_for('profile'))
    
    token_url = "https://id.twitch.tv/oauth2/token"
    data = {
        'client_id': TWITCH_CLIENT_ID,
        'client_secret': TWITCH_CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    
    try:
        resp = requests.post(token_url, data=data)
        token_data = resp.json()
        
        if 'access_token' not in token_data:
            flash('Ошибка получения токена для проверки', 'danger')
            return redirect(url_for('profile'))
        
        app_token = token_data['access_token']
        headers = {'Client-Id': TWITCH_CLIENT_ID, 'Authorization': f'Bearer {app_token}'}
        
        channel_name = "3guys3vibes"
        channel_resp = requests.get(f'https://api.twitch.tv/helix/users?login={channel_name}', headers=headers)
        channel_data = channel_resp.json()
        
        if not channel_data.get('data'):
            flash('Канал не найден', 'danger')
            return redirect(url_for('profile'))
        
        channel_id = channel_data['data'][0]['id']
        
        user_resp = requests.get(f'https://api.twitch.tv/helix/users?login={user.twitch_username}', headers=headers)
        user_data = user_resp.json()
        
        if not user_data.get('data'):
            flash(f'Пользователь @{user.twitch_username} не найден в Twitch', 'danger')
            return redirect(url_for('profile'))
        
        user_id = user_data['data'][0]['id']
        
        sub_resp = requests.get(
            f'https://api.twitch.tv/helix/subscriptions/user?broadcaster_id={channel_id}&user_id={user_id}',
            headers=headers
        )
        
        if sub_resp.status_code == 200:
            user.twitch_subscribed = True
            db.session.commit()
            flash('Подписка подтверждена! Теперь вы можете скачать SHIFT 325.', 'success')
        else:
            user.twitch_subscribed = False
            db.session.commit()
            flash(f'Вы не подписаны на канал {channel_name}. Подпишитесь и проверьте снова.', 'warning')
            
    except Exception as e:
        flash(f'Ошибка проверки: {str(e)}', 'danger')
    
    return redirect(url_for('profile'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5555, debug=True)