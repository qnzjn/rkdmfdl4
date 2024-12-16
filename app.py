from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
import google.generativeai as genai
from datetime import datetime, timedelta
from markupsafe import Markup
import re
from collections import defaultdict
from time import time
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os
import random
import string
from werkzeug.utils import secure_filename

app = Flask(__name__)
# 안전한 랜덤 시크릿 키 생성
app.secret_key = 'your_secure_secret_key_here'  # 실제 운영시에는 더 안전한 값 사용

# 세션 설정
app.permanent_session_lifetime = timedelta(days=7)  # 세션 유지 기간 설정

@app.before_request
def before_request():
    # 세션에 user_id가 있지만 users 딕셔너리에 없는 경우 세션 삭제
    if 'user_id' in session and session['user_id'] not in users:
        session.pop('user_id', None)

# Gemini API 설정
GOOGLE_API_KEY = 'AIzaSyAh_G938P1TiEn2VRClDY24fLYha0-shVo'
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# 임시 데이터 저장소
posts = []

# 게시글 및 댓글 제한 설
POST_LIMIT_TIME = 30  # 초 단위
POST_LIMIT_COUNT = 3  # 시간 내 최대 게시글 수
COMMENT_LIMIT_TIME = 15  # 초 단위
COMMENT_LIMIT_COUNT = 5  # 시간 내 최대 댓글 수

# 사용자별 게시글/댓글 작성 기록
post_history = defaultdict(list)
comment_history = defaultdict(list)

# 욕설 필터링 (예시 목록)
BAD_WORDS = {
    '바보', '청이', '욕설', '나쁜말',  # 실제 운영시에는 더 많은 욕설 단어 추가
}

# 도배 패턴 감지
def is_spam_pattern(text):
    # 같은 문자가 연속으로 4번 이상 복
    if re.search(r'(.)\1{3,}', text):
        return True
    # 같은 단어가 3번 이상 반복
    words = text.split()
    if len(words) >= 3:
        for i in range(len(words)-2):
            if words[i] == words[i+1] == words[i+2]:
                return True
    return False

# 욕설 필터링
def contains_bad_words(text):
    return any(word in text.lower() for word in BAD_WORDS)

# 도배 방지 (시간 기반)
def check_spam_by_time(history, limit_time, limit_count, current_time):
    # 만료된 기록 제거
    history[:] = [t for t in history if current_time - t < limit_time]
    # 제한 시간 내 게시물 수 확인
    return len(history) >= limit_count

# nl2br 필터 추가
@app.template_filter('nl2br')
def nl2br_filter(text):
    if not text:
        return text
    return Markup(text.replace('\n', '<br>'))

# 임시 사용자 데이터 저장소 (실제로는 데이터베이스 사용)
users = {}

# 로그인 필수 데코레이터
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('로그인이 필요한 서비스입니다.')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# 로그인 필수 데코레이터 아래에 추가
def profile_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('로그인이 필요한 서비스입니다.')
            return redirect(url_for('login'))
        
        user = users[session['user_id']]
        if not user['profile'].get('pet_name'):
            flash('서비스 이용을 위해 프로필을 완성해주세요.')
            return redirect(url_for('edit_profile'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        remember = request.form.get('remember')  # 로그인 상태 유지 체크 여부
        
        if user_id in users and check_password_hash(users[user_id]['password'], password):
            session.permanent = True  # 세션 영구 설정
            if remember:  # 로그인 상태 유지가 체크되었을 경우
                # 30일 동안 세션 유지
                app.permanent_session_lifetime = timedelta(days=30)
            else:
                # 기본값으로 7일 유지
                app.permanent_session_lifetime = timedelta(days=7)
            
            session['user_id'] = user_id
            flash('로그인되었습니다.')
            return redirect(url_for('index'))
        flash('아이디 또는 비밀번호가 올바르지 않습니다.')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        nickname = request.form.get('nickname')
        
        # 유효성 검사
        if user_id in users:
            flash('이미 존재하는 아이디입니다.')
            return redirect(url_for('register'))
            
        if any(user['nickname'] == nickname for user in users.values()):
            flash('이미 존재하는 닉네임입니다.')
            return redirect(url_for('register'))
            
        if password != password_confirm:
            flash('비밀번호가 일치하지 않습니다.')
            return redirect(url_for('register'))
            
        if len(password) < 8:
            flash('비밀번호는 8자 이상이어야 합니다.')
            return redirect(url_for('register'))
            
        # 사용자 등록 - 프로필 정보 초기화 추가
        users[user_id] = {
            'password': generate_password_hash(password),
            'nickname': nickname,
            'profile': {
                'pet_type': '',
                'pet_name': '',
                'pet_age': '',
                'bio': '',
                'profile_image': 'default.jpg'
            }
        }
        
        # 자동 로그인
        session['user_id'] = user_id
        flash('회원가입이 완료되었습니다. 프로필을 설정해주세요.')
        return redirect(url_for('edit_profile'))
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('로그아웃되었습니다.')
    return redirect(url_for('index'))

@app.route('/')
def index():
    return render_template('index.html', users=users)

@app.route('/chat', methods=['POST'])
@login_required
@profile_required
def chat():
    try:
        data = request.json
        user_message = data.get('message', '')
        pet_type = data.get('pet_type', 'dog')
        category = data.get('category', 'general')
        
        # 프롬프트 구성
        prompt = f"""
        당신은 수의사 자격 가진 전문 반려동물 건강 상담 AI입니다.
        15년 이상의 임상 경험을 바탕으로 전문적이고 정확한 조언을 제공합니다.

        상담 정보:
        - 반려동물 종: {pet_type}
        - 상담 카테고리: {category}
        - 보호자의 질문: {user_message}

        다음 가이드라인에 따라 답변해주세요:

        1. 응답 구조:
           - 증상/상황 파악 및 공감
           - 전문적 설명과 언
           - 필요한 경우 주의사항이나 예방법 제시
           - 수의사 방문이 필요한 경우 명확히 안내

        2. 답변 스타일:
           - 전문적이면서도 이해하기 쉬운 설명
           - 따뜻하고 공감적인 어조 유지
           - 구체적인 예시나 비유 활용
           - 불필요한 의학 전문용어 자제

        3. 안 고려사항:
           - 응급상황 여 판단하여 우선순위 제시
           - 위험할 수 있는 자가진단/치료 주의
           - 필요시 전문의 상담 권고

        4. 형식 구사항:
           - 마크다운이나 특수문자 사용하지 않기
           - 자연스러운 대화체 사용
           - 명확한 단락 구분
           - 핵심 정보는 간단명료하게 전달

        {pet_type}의 {category} 카테고리에 맞춰, 보호자의 질문에 전문적이고 상세한 답변을 제공해주세요.
        """
        
        # Gemini API로 응답 생성
        response = model.generate_content(prompt)
        
        # 마크다운 형식 제거
        response_text = response.text.replace('*', '').replace('**', '').replace('`', '')
        
        return jsonify({
            'success': True,
            'response': response_text
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/services')
@login_required
@profile_required
def services():
    return render_template('services.html')

@app.route('/health_consult')
@login_required
@profile_required
def health_consult():
    return render_template('health_consult.html')

@app.route('/emergency')
@login_required
@profile_required
def emergency():
    return render_template('emergency.html')

@app.route('/nutrition')
@login_required
@profile_required
def nutrition():
    return render_template('nutrition.html')

# 페이지당 게시글 수 설정
POSTS_PER_PAGE = 10

@app.route('/board')
@app.route('/board/<int:page>')
@login_required
def board(page=1):
    # 전체 게시글을 최신순으로 정렬
    sorted_posts = sorted(posts, key=lambda x: x['id'], reverse=True)
    
    # 전체 페이지 수 계산
    total_pages = (len(sorted_posts) + POSTS_PER_PAGE - 1) // POSTS_PER_PAGE
    
    # 현재 페이지의 게시글 목록
    start_idx = (page - 1) * POSTS_PER_PAGE
    end_idx = start_idx + POSTS_PER_PAGE
    current_posts = sorted_posts[start_idx:end_idx]
    
    return render_template('board.html', 
                         posts=current_posts,
                         current_page=page,
                         total_pages=total_pages)

# posts 리스트 위에 전역 변수로 추가
post_counter = 1  # 게시글 번호 카운터

@app.route('/write', methods=['GET', 'POST'])
@login_required
def write_post():
    global post_counter  # 전역 변수 사용 선언
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        current_time = time()
        user_ip = request.remote_addr

        # 도배 검사
        if check_spam_by_time(post_history[user_ip], POST_LIMIT_TIME, POST_LIMIT_COUNT, current_time):
            flash(f'게시글은 {POST_LIMIT_TIME}초 동안 {POST_LIMIT_COUNT}개만 작성할 수 있습니다.')
            return redirect(url_for('write_post'))

        # 욕설 검사
        if contains_bad_words(title) or contains_bad_words(content):
            flash('부적절한 단어가 포함되어 있습니다.')
            return redirect(url_for('write_post'))

        # 도배 패턴 검사
        if is_spam_pattern(title) or is_spam_pattern(content):
            flash('도배성 게시글은 작성할 수 없습니다.')
            return redirect(url_for('write_post'))

        # 게시글 작성 시 자동 번호 부여
        post = {
            'id': post_counter,  # 자동 ��가하는 번호 사용
            'title': title,
            'content': content,
            'category': request.form.get('category'),
            'author': users[session['user_id']]['nickname'],
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'comments': []
        }
        posts.append(post)
        post_counter += 1  # 번호 증가
        post_history[user_ip].append(current_time)
        return redirect(url_for('board'))
    return render_template('write.html')

@app.route('/post/<int:post_id>')
@login_required
def view_post(post_id):
    post = next((post for post in posts if post['id'] == post_id), None)
    if post:
        return render_template('post_view.html', post=post, users=users)
    return redirect(url_for('board'))

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    content = request.form.get('comment', '')
    current_time = time()
    user_ip = request.remote_addr

    # 도배 검사
    if check_spam_by_time(comment_history[user_ip], COMMENT_LIMIT_TIME, COMMENT_LIMIT_COUNT, current_time):
        flash(f'댓글은 {COMMENT_LIMIT_TIME}초 동안 {COMMENT_LIMIT_COUNT}개만 작성할 수 있습니다.')
        return redirect(url_for('view_post', post_id=post_id))

    # 욕설 검사
    if contains_bad_words(content):
        flash('부적절한 단어가 포함되어 있습니다.')
        return redirect(url_for('view_post', post_id=post_id))

    # 도배 패턴 검사
    if is_spam_pattern(content):
        flash('도배성 댓글은 작성할 수 없습니다.')
        return redirect(url_for('view_post', post_id=post_id))

    post = next((post for post in posts if post['id'] == post_id), None)
    if post:
        comment = {
            'id': len(post['comments']) + 1,
            'content': content,
            'author': users[session['user_id']]['nickname'],  # 로그인한 사용자의 닉네임
            'date': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        post['comments'].append(comment)
        comment_history[user_ip].append(current_time)
    return redirect(url_for('view_post', post_id=post_id))

# 게시글 삭제
@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    global posts  # global 선언을 함수 시작 부분으로 이동
    # 작성자 본인만 삭제할 수 있도록 검사
    post = next((post for post in posts if post['id'] == post_id), None)
    if post and post['author'] == users[session['user_id']]['nickname']:
        posts = [p for p in posts if p['id'] != post_id]
        flash('게시글이 삭제되었습니다.')
    else:
        flash('삭제 권한이 없습니다.')
    return redirect(url_for('board'))

# 댓글 삭제
@app.route('/post/<int:post_id>/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(post_id, comment_id):
    post = next((post for post in posts if post['id'] == post_id), None)
    if post:
        comment = next((c for c in post['comments'] if c['id'] == comment_id), None)
        if comment and comment['author'] == users[session['user_id']]['nickname']:
            post['comments'] = [c for c in post['comments'] if c['id'] != comment_id]
            flash('댓글이 삭제되었습니다.')
        else:
            flash('삭제 권한이 없습니다.')
    return redirect(url_for('view_post', post_id=post_id))

@app.route('/check_duplicate', methods=['POST'])
def check_duplicate():
    user_id = request.form.get('user_id')
    nickname = request.form.get('nickname')
    
    if user_id:
        if user_id in users:
            return jsonify({'exists': True, 'message': '이미 사용 중인 아이디입니다.'})
        return jsonify({'exists': False})
        
    if nickname:
        if any(user['nickname'] == nickname for user in users.values()):
            return jsonify({'exists': True, 'message': '이미 사용 중인 닉네임입니다.'})
        return jsonify({'exists': False})

@app.context_processor
def inject_user():
    return dict(users=users)

# 임시 비밀번호 생성 함수
def generate_temp_password():
    # 숫자 8자리 생성
    return ''.join(random.choices(string.digits, k=8))

@app.route('/find_id', methods=['GET', 'POST'])
def find_id():
    if request.method == 'POST':
        nickname = request.form.get('nickname')
        # 닉네임으로 아이디 찾기
        found_users = [user_id for user_id, user in users.items() if user['nickname'] == nickname]
        if found_users:
            return render_template('find_id.html', found_users=found_users)
        else:
            flash('해당 닉네임으로 등록된 아이디가 없습니다.')
    return render_template('find_id.html')

@app.route('/find_password', methods=['GET', 'POST'])
def find_password():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        nickname = request.form.get('nickname')
        
        # 아이디와 닉네임이 일치하는지 확인
        if user_id in users and users[user_id]['nickname'] == nickname:
            # 임시 비밀번호 생성
            temp_password = generate_temp_password()
            # 비밀번호 업데이트
            users[user_id]['password'] = generate_password_hash(temp_password)
            return render_template('find_password.html', temp_password=temp_password)
        else:
            flash('입력하신 정보와 일치하는 계정이 없습니다.')
    return render_template('find_password.html')

# 프로필 관련 라우트 추가
@app.route('/profile')
@login_required
def profile():
    user_data = users[session['user_id']]
    
    # 사용자의 게시글 수 계산
    user_posts = [post for post in posts if post['author'] == user_data['nickname']]
    post_count = len(user_posts)
    
    # 사용자의 댓글 수 계산
    comment_count = 0
    for post in posts:
        comment_count += sum(1 for comment in post['comments'] 
                           if comment['author'] == user_data['nickname'])
    
    return render_template('profile.html', 
                         user=user_data,
                         post_count=post_count,
                         comment_count=comment_count)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        user = users[session['user_id']]
        
        # 프로필 정보 업데이트
        user['profile'].update({
            'pet_type': request.form.get('pet_type', ''),
            'pet_name': request.form.get('pet_name', ''),
            'pet_age': request.form.get('pet_age', ''),
            'bio': request.form.get('bio', '')
        })

        # 프로필 이미지 처리
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(file_path)
                user['profile']['profile_image'] = filename

        flash('프로필이 업데이트되었습니다.')
        return redirect(url_for('profile'))
    
    return render_template('edit_profile.html', user=users[session['user_id']])

# 프로필 이미지 업로드를 위한 설정
UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# uploads 디렉토리가 없으면 생성
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if __name__ == '__main__':
    app.run(debug=True) 