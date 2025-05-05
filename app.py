from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, UnfilteredPost, Mood, Poll, Comment, PollVote, FriendRequest, MoodReaction, Block, post_reactions, VibePing, Notification
import os
import json
from datetime import datetime, timedelta, date
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string
from flask_mail import Mail, Message
from flask_migrate import Migrate
from PIL import Image
import io

app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-please-change')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///mood_app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov'}

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'  # Replace with your email
app.config['MAIL_PASSWORD'] = 'your-app-password'  # Replace with your app password
app.config['MAIL_DEFAULT_SENDER'] = 'your-email@gmail.com'  # Replace with your email

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db.init_app(app)
migrate = Migrate(app, db)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
mail = Mail(app)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template('index.html')

@app.route('/home')
@login_required
def home():
    # Get user's stats
    user_moods = Mood.query.filter_by(author=current_user).all()
    user_posts = UnfilteredPost.query.filter_by(author=current_user).order_by(UnfilteredPost.created_at.desc()).all()
    user_polls = Poll.query.filter_by(author=current_user).all()
    
    # Get feed items (moods, posts, and polls from friends)
    feed_items = []
    
    # Get user's recent content (moods, posts, polls)
    recent_moods = Mood.query.filter_by(author=current_user).order_by(desc(Mood.created_at)).limit(10).all()
    for mood in recent_moods:
        mood.type = 'mood'
        mood.author = current_user
        feed_items.append(mood)
    
    recent_posts = UnfilteredPost.query.filter_by(author=current_user).order_by(desc(UnfilteredPost.created_at)).limit(10).all()
    for post in recent_posts:
        post.type = 'post'
        post.author = current_user
        feed_items.append(post)
    
    recent_polls = Poll.query.filter_by(author=current_user).order_by(desc(Poll.created_at)).limit(10).all()
    for poll in recent_polls:
        poll.type = 'poll'
        poll.author = current_user
        feed_items.append(poll)
    
    # Get moods from friends
    for friend in current_user.friends:
        friend_moods = Mood.query.filter_by(author=friend).order_by(desc(Mood.created_at)).limit(10).all()
        for mood in friend_moods:
            mood.type = 'mood'
            mood.author = friend
            feed_items.append(mood)
    
    # Get posts from friends
    for friend in current_user.friends:
        friend_posts = UnfilteredPost.query.filter_by(author=friend).order_by(desc(UnfilteredPost.created_at)).limit(10).all()
        for post in friend_posts:
            post.type = 'post'
            post.author = friend
            feed_items.append(post)
    
    # Get polls from friends
    for friend in current_user.friends:
        friend_polls = Poll.query.filter_by(author=friend).order_by(desc(Poll.created_at)).limit(10).all()
        for poll in friend_polls:
            poll.type = 'poll'
            poll.author = friend
            feed_items.append(poll)
    
    # Sort feed items by creation date
    feed_items.sort(key=lambda x: x.created_at, reverse=True)
    
    # Check if user has recent content (within the last 24 hours)
    has_recent_content = False
    if feed_items and (datetime.utcnow() - feed_items[0].created_at).total_seconds() < 86400:  # 24 hours in seconds
        has_recent_content = True
    
    # Get suggested friends (users who are not friends yet)
    suggested_friends = User.query.filter(
        User.id != current_user.id,
        ~User.friends.any(User.id == current_user.id)
    ).limit(5).all()
    
    # Get trending moods (moods with most reactions)
    trending_moods = db.session.query(Mood, func.count(MoodReaction.id).label('reaction_count'))\
        .outerjoin(MoodReaction)\
        .group_by(Mood.id)\
        .order_by(desc('reaction_count'))\
        .limit(5).all()
    
    trending_moods = [mood for mood, count in trending_moods]
    
    return render_template('home.html',
                          user_moods=user_moods,
                          user_posts=user_posts,
                          user_polls=user_polls,
                          feed_items=feed_items,
                          suggested_friends=suggested_friends,
                          trending_moods=trending_moods,
                          has_recent_content=has_recent_content)

@app.route('/dashboard')
@login_required
def dashboard():
    # Get user's moods
    user_moods = Mood.query.filter_by(author=current_user).order_by(Mood.created_at.desc()).limit(5).all()
    
    # Get user's posts (excluding archived ones)
    user_posts = UnfilteredPost.query.filter_by(
        user_id=current_user.id,
        is_archived=False
    ).order_by(UnfilteredPost.created_at.desc()).limit(5).all()
    
    # Get user's archived posts
    archived_posts = UnfilteredPost.query.filter_by(
        user_id=current_user.id,
        is_archived=True
    ).order_by(UnfilteredPost.created_at.desc()).all()
    
    # Get user's polls
    user_polls = Poll.query.filter_by(author=current_user).order_by(Poll.created_at.desc()).limit(5).all()
    
    # Get friends' moods
    friends_moods = []
    for friend in current_user.friends:
        friend_moods = Mood.query.filter_by(author=friend).order_by(Mood.created_at.desc()).limit(2).all()
        friends_moods.extend(friend_moods)
    friends_moods.sort(key=lambda x: x.created_at, reverse=True)
    friends_moods = friends_moods[:5]
    
    return render_template('dashboard.html',
                         user_moods=user_moods,
                         user_posts=user_posts,
                         archived_posts=archived_posts,
                         user_polls=user_polls,
                         friends_moods=friends_moods)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        password = request.form.get('password')
        
        # Try to find user by email or username
        user = User.query.filter(
            (User.email == identifier) | (User.username == identifier)
        ).first()
        
        if user and user.check_password(password):
            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('home'))  # Redirect to home after login
        flash('Invalid username/email or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            email = request.form.get('email')
            username = request.form.get('username')
            password = request.form.get('password')
            date_of_birth = request.form.get('date_of_birth')
            
            # Validate age
            dob = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
            today = date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            
            if age < 18:
                flash('You must be 18 years or older to register.')
                return redirect(url_for('register'))
            
            if User.query.filter_by(email=email).first():
                flash('Email already registered')
                return redirect(url_for('register'))
                
            if User.query.filter_by(username=username).first():
                flash('Username already taken')
                return redirect(url_for('register'))
            
            user = User(email=email, username=username, date_of_birth=dob)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            
            login_user(user)
            return redirect(url_for('home'))  # Redirect to home after registration
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.')
            print(f"Registration error: {str(e)}")
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/create_mood', methods=['POST'])
@login_required
def create_mood():
    try:
        emoji = request.form.get('emoji')
        caption = request.form.get('caption')
        song = request.form.get('song')
        
        mood = Mood(
            emoji=emoji,
            caption=caption,
            author=current_user
        )
        
        # Handle song input
        if song:
            # In a real app, you might want to search for the song on a music service
            # For now, we'll just store the song name as is
            mood.song_url = song
        
        db.session.add(mood)
        db.session.commit()
        
        flash('Your mood has been shared!', 'success')
        return redirect(url_for('home'))
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('home'))

@app.route('/create_post', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        try:
            # Get form data
            caption = request.form.get('caption')
            allow_comments = request.form.get('allow_comments') == 'on'
            is_public = request.form.get('is_public') == 'on'
            is_compressed = request.form.get('compressed') == 'true'
            
            # Handle file upload
            if 'media' not in request.files:
                flash('No file uploaded')
                return redirect(request.url)
                
            file = request.files['media']
            if file.filename == '':
                flash('No file selected')
                return redirect(request.url)
                
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to filename to make it unique
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                filename = f"{timestamp}_{filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Determine media type
                media_type = 'video' if filename.lower().endswith(('.mp4', '.mov')) else 'photo'
                
                # If it's an image and not already compressed, apply server-side compression
                if media_type == 'photo' and not is_compressed:
                    try:
                        # Server-side image compression using Pillow
                        img = Image.open(file)
                        # Resize if needed
                        max_size = (800, 800)
                        img.thumbnail(max_size, Image.LANCZOS)
                        
                        # Compress
                        output = io.BytesIO()
                        img.save(output, format='JPEG', quality=70, optimize=True)
                        output.seek(0)
                        
                        # Save the compressed image
                        with open(file_path, 'wb') as f:
                            f.write(output.getvalue())
                    except Exception as e:
                        # If compression fails, save the original file
                        file.save(file_path)
                        print(f"Image compression error: {str(e)}")
                else:
                    # Save the file as is (either it's a video or already compressed)
                    file.save(file_path)
                
                # Create post
                post = UnfilteredPost(
                    user_id=current_user.id,
                    media_url=url_for('static', filename=f'uploads/{filename}'),
                    media_type=media_type,
                    caption=caption,
                    is_public=is_public,
                    allow_comments=allow_comments,
                    is_one_shot=True,  # Always true for new posts
                    created_at=datetime.utcnow()
                )
                
                db.session.add(post)
                db.session.commit()
                
                flash('Your post has been shared!')
                return redirect(url_for('home'))
            else:
                flash('File type not allowed')
                return redirect(request.url)
        except Exception as e:
            db.session.rollback()
            flash('An error occurred while sharing your post. Please try again.')
            print(f"Post creation error: {str(e)}")
            return redirect(request.url)
    
    return render_template('create_post.html')

@app.route('/post/<int:post_id>')
@login_required
def view_post(post_id):
    post = UnfilteredPost.query.get_or_404(post_id)
    
    # Check if user has permission to view the post
    if not post.is_public and post.user_id != current_user.id and post.author not in current_user.friends:
        flash('You do not have permission to view this post')
        return redirect(url_for('home'))
    
    return render_template('view_post.html', post=post)

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = UnfilteredPost.query.get_or_404(post_id)
    
    # Check if comments are allowed
    if not post.allow_comments:
        flash('Comments are disabled for this post')
        return redirect(url_for('view_post', post_id=post_id))
    
    content = request.form.get('content')
    if not content:
        flash('Comment cannot be empty')
        return redirect(url_for('view_post', post_id=post_id))
    
    comment = Comment(
        user_id=current_user.id,
        content=content,
        post_id=post_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    return redirect(url_for('view_post', post_id=post_id))

@app.route('/post/<int:post_id>/react', methods=['POST'])
@login_required
def react_to_post(post_id):
    post = UnfilteredPost.query.get_or_404(post_id)
    reaction_type = request.form.get('reaction_type')
    
    # Check if user already reacted
    existing_reaction = db.session.query(post_reactions).filter_by(
        post_id=post_id,
        user_id=current_user.id
    ).first()
    
    if existing_reaction:
        # Remove existing reaction
        db.session.execute(
            post_reactions.delete().where(
                (post_reactions.c.post_id == post_id) &
                (post_reactions.c.user_id == current_user.id)
            )
        )
        db.session.commit()
        return jsonify({'status': 'removed'})
    
    # Add new reaction
    db.session.execute(
        post_reactions.insert().values(
            post_id=post_id,
            user_id=current_user.id
        )
    )
    db.session.commit()
    
    return jsonify({'status': 'added'})

@app.route('/edit_profile', methods=['POST'])
@login_required
def edit_profile():
    try:
        # Get form data
        username = request.form.get('username')
        bio = request.form.get('bio')
        is_public_profile = request.form.get('is_public_profile') == 'on'
        
        # Check if username is already taken by another user
        existing_user = User.query.filter(User.username == username, User.id != current_user.id).first()
        if existing_user:
            flash('Username is already taken. Please choose another one.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Update user profile
        current_user.username = username
        current_user.bio = bio
        current_user.is_public_profile = is_public_profile
        
        # Handle profile picture upload
        if 'profile_picture' in request.files:
            file = request.files['profile_picture']
            if file and file.filename != '':
                if allowed_file(file.filename):
                    # Create a secure filename
                    filename = secure_filename(file.filename)
                    # Add timestamp to make filename unique
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = f"profile_{current_user.id}_{timestamp}_{filename}"
                    
                    # Save the file
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    
                    # Update user's profile picture URL
                    current_user.profile_picture = url_for('static', filename=f'uploads/{filename}')
                else:
                    flash('Invalid file type. Please upload an image.', 'danger')
                    return redirect(url_for('dashboard'))
        
        # Save changes to database
        db.session.commit()
        
        flash('Your profile has been updated successfully!', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/profile/<username>')
@login_required
def view_profile(username):
    try:
        profile_user = User.query.filter_by(username=username).first_or_404()
        
        # Check if the profile is accessible
        if not profile_user.is_public_profile and not current_user.is_friend(profile_user) and profile_user.id != current_user.id:
            flash('This profile is private. You need to be friends to view it.', 'warning')
            return redirect(url_for('profiles'))
        
        # Get user's content
        user_moods = profile_user.moods.order_by(Mood.created_at.desc()).limit(4).all()
        user_posts = profile_user.posts.order_by(UnfilteredPost.created_at.desc()).limit(4).all()
        user_polls = profile_user.polls.order_by(Poll.created_at.desc()).limit(4).all()
        
        # Get suggested friends (excluding current user and existing friends)
        suggested_friends = User.query.filter(
            User.id != current_user.id,
            User.is_public_profile == True,
            ~User.friends.contains(current_user)
        ).limit(5).all()
        
        # Check if current user is friends with profile user
        is_friend = current_user.is_friend(profile_user)
        
        return render_template('user_profile.html',
                             profile_user=profile_user,
                             user_moods=user_moods,
                             user_posts=user_posts,
                             user_polls=user_polls,
                             suggested_friends=suggested_friends,
                             is_friend=is_friend)
                             
    except Exception as e:
        print(e);
        app.logger.error(f"Error viewing profile: {str(e)}")
        flash('An error occurred while loading the profile.', 'error')
        return redirect(url_for('profiles'))

@app.route('/create_poll', methods=['GET', 'POST'])
@login_required
def create_poll():
    if request.method == 'POST':
        try:
            # Get form data
            question = request.form.get('question')
            options = request.form.getlist('options[]')
            is_anonymous = request.form.get('is_anonymous') == 'on'
            is_public = request.form.get('is_public') == 'on'
            
            # Handle image upload if provided
            image_url = None
            if 'image' in request.files:
                file = request.files['image']
                if file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Add timestamp to filename to make it unique
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = f"{timestamp}_{filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)
                    image_url = url_for('static', filename=f'uploads/{filename}')
            
            # Create poll
            poll = Poll(
                user_id=current_user.id,
                question=question,
                options=json.dumps(options),
                image_url=image_url,
                is_anonymous=is_anonymous,
                is_public=is_public,
                created_at=datetime.utcnow()
            )
            
            db.session.add(poll)
            db.session.commit()
            
            flash('Your poll has been created!')
            return redirect(url_for('home'))
            
        except Exception as e:
            flash('An error occurred while creating your poll. Please try again.')
            return redirect(request.url)
    
    return render_template('create_poll.html')

@app.route('/poll/<int:poll_id>/vote', methods=['POST'])
@login_required
def vote_poll(poll_id):
    try:
        poll = Poll.query.get_or_404(poll_id)
        
        # Get option_index from JSON data
        data = request.get_json()
        if not data or 'option_index' not in data:
            return jsonify({'status': 'error', 'message': 'Missing option_index'}), 400
            
        option_index = data['option_index']
        
        # Check if user has already voted
        existing_vote = PollVote.query.filter_by(
            poll_id=poll_id,
            user_id=current_user.id
        ).first()
        
        if existing_vote:
            # Update existing vote
            existing_vote.option_index = option_index
        else:
            # Create new vote
            vote = PollVote(
                poll_id=poll_id,
                user_id=current_user.id,
                option_index=option_index
            )
            db.session.add(vote)
        
        db.session.commit()
        
        # Calculate vote percentages
        total_votes = poll.votes.count()
        vote_counts = {}
        for i in range(len(poll.options_list)):
            count = PollVote.query.filter_by(poll_id=poll_id, option_index=i).count()
            vote_counts[i] = {
                'count': count,
                'percentage': (count / total_votes * 100) if total_votes > 0 else 0
            }
        
        return jsonify({
            'status': 'success',
            'total_votes': total_votes,
            'vote_counts': vote_counts,
            'user_vote': option_index
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    # Validate current password
    if not current_user.check_password(current_password):
        flash('Current password is incorrect', 'danger')
        return redirect(url_for('dashboard'))
    
    # Validate new password
    if new_password != confirm_password:
        flash('New passwords do not match', 'danger')
        return redirect(url_for('dashboard'))
    
    # Validate password strength
    if len(new_password) < 8:
        flash('Password must be at least 8 characters long', 'danger')
        return redirect(url_for('dashboard'))
    
    # Update password
    current_user.set_password(new_password)
    db.session.commit()
    
    flash('Your password has been updated successfully', 'success')
    return redirect(url_for('dashboard'))

@app.route('/load_more')
@login_required
def load_more():
    page = request.args.get('page', 1, type=int)
    per_page = 10  # Increased from 5 to 10 items per page
    
    # Get the user's recent content (moods, posts, polls)
    user_moods = Mood.query.filter_by(author=current_user).order_by(Mood.created_at.desc()).all()
    user_posts = UnfilteredPost.query.filter_by(author=current_user).order_by(UnfilteredPost.created_at.desc()).all()
    user_polls = Poll.query.filter_by(author=current_user).order_by(Poll.created_at.desc()).all()
    
    # Get content from friends
    friends_content = []
    for friend in current_user.friends:
        friend_moods = Mood.query.filter_by(author=friend).order_by(Mood.created_at.desc()).all()
        friend_posts = UnfilteredPost.query.filter_by(author=friend).order_by(UnfilteredPost.created_at.desc()).all()
        friend_polls = Poll.query.filter_by(author=friend).order_by(Poll.created_at.desc()).all()
        
        for mood in friend_moods:
            friends_content.append({
                'type': 'mood',
                'id': mood.id,
                'author': {
                    'id': friend.id,
                    'username': friend.username,
                    'profile_picture': friend.profile_picture
                },
                'emoji': mood.emoji,
                'caption': mood.caption,
                'photo_url': mood.photo_url,
                'song_url': mood.song_url,
                'created_at': mood.created_at.strftime('%Y-%m-%d %H:%M'),
                'reactions_count': mood.reactions.count()
            })
        
        for post in friend_posts:
            friends_content.append({
                'type': 'post',
                'id': post.id,
                'author': {
                    'id': friend.id,
                    'username': friend.username,
                    'profile_picture': friend.profile_picture
                },
                'media_type': post.media_type,
                'media_url': post.media_url,
                'display_media_url': post.display_media_url,
                'caption': post.caption,
                'is_public': post.is_public,
                'created_at': post.created_at.strftime('%Y-%m-%d %H:%M'),
                'reactions_count': post.reactions.count(),
                'comments_count': post.comments.count()
            })
        
        for poll in friend_polls:
            friends_content.append({
                'type': 'poll',
                'id': poll.id,
                'author': {
                    'id': friend.id,
                    'username': friend.username,
                    'profile_picture': friend.profile_picture
                },
                'question': poll.question,
                'options_list': poll.options_list,
                'image_url': poll.image_url,
                'created_at': poll.created_at.strftime('%Y-%m-%d %H:%M'),
                'votes_count': poll.votes.count()
            })
    
    # Combine all content
    all_content = []
    
    # Add user's content
    for mood in user_moods:
        all_content.append({
            'type': 'mood',
            'id': mood.id,
            'author': {
                'id': current_user.id,
                'username': current_user.username,
                'profile_picture': current_user.profile_picture
            },
            'emoji': mood.emoji,
            'caption': mood.caption,
            'photo_url': mood.photo_url,
            'song_url': mood.song_url,
            'created_at': mood.created_at.strftime('%Y-%m-%d %H:%M'),
            'reactions_count': mood.reactions.count()
        })
    
    for post in user_posts:
        all_content.append({
            'type': 'post',
            'id': post.id,
            'author': {
                'id': current_user.id,
                'username': current_user.username,
                'profile_picture': current_user.profile_picture
            },
            'media_type': post.media_type,
            'media_url': post.media_url,
            'display_media_url': post.display_media_url,
            'caption': post.caption,
            'is_public': post.is_public,
            'created_at': post.created_at.strftime('%Y-%m-%d %H:%M'),
            'reactions_count': post.reactions.count(),
            'comments_count': post.comments.count()
        })
    
    for poll in user_polls:
        all_content.append({
            'type': 'poll',
            'id': poll.id,
            'author': {
                'id': current_user.id,
                'username': current_user.username,
                'profile_picture': current_user.profile_picture
            },
            'question': poll.question,
            'options_list': poll.options_list,
            'image_url': poll.image_url,
            'created_at': poll.created_at.strftime('%Y-%m-%d %H:%M'),
            'votes_count': poll.votes.count()
        })
    
    # Add friends' content
    all_content.extend(friends_content)
    
    # Sort by creation date
    all_content.sort(key=lambda x: x['created_at'], reverse=True)
    
    # Paginate the content
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_content = all_content[start_idx:end_idx]
    
    # Check if there are more items
    has_more = end_idx < len(all_content)
    
    return jsonify({
        'items': paginated_content,
        'has_more': has_more,
        'total_items': len(all_content),
        'current_page': page,
        'total_pages': (len(all_content) + per_page - 1) // per_page
    })

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        # Try to find user by email or username
        user = User.query.filter(
            (User.email == identifier) | (User.username == identifier)
        ).first()
        
        if user:
            # Generate a random token
            token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
            user.reset_token = token
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            
            # Send email with reset link
            reset_url = url_for('reset_password', token=token, _external=True)
            msg = Message('Password Reset Request',
                         recipients=[user.email])
            msg.body = f'''To reset your password, visit the following link:
{reset_url}

If you did not make this request, please ignore this email.
'''
            mail.send(msg)
            
            flash('An email has been sent with instructions to reset your password.', 'info')
            return redirect(url_for('login'))
        
        flash('Email address not found.', 'error')
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or user.reset_token_expiry < datetime.utcnow():
        flash('Invalid or expired reset token. Please request a new one.', 'error')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('reset_password', token=token))
        
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        flash('Your password has been reset successfully.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html')

@app.route('/unfriend/<int:user_id>', methods=['POST'])
@login_required
def unfriend(user_id):
    try:
        user = User.query.get_or_404(user_id)
        
        if user == current_user:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'status': 'error', 'message': 'Invalid action'})
            flash('Invalid action', 'danger')
            return redirect(url_for('view_profile', username=user.username))
        
        if user in current_user.friends:
            current_user.friends.remove(user)
            user.friends.remove(current_user)
            db.session.commit()
            message = 'Friend removed successfully'
            success = True
        else:
            message = 'User is not in your friends list'
            success = False
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'success' if success else 'error', 'message': message})
        
        flash(message, 'success' if success else 'danger')
        return redirect(url_for('view_profile', username=user.username))
    except Exception as e:
        app.logger.error(f"Error in unfriend: {str(e)}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'An error occurred while unfriending the user'})
        flash('An error occurred while unfriending the user', 'danger')
        return redirect(url_for('friends_management'))

@app.route('/send-friend-request/<int:user_id>', methods=['POST'])
@login_required
def send_friend_request(user_id):
    user = User.query.get_or_404(user_id)
    
    if user == current_user:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'You cannot send a friend request to yourself'})
        flash('You cannot send a friend request to yourself', 'danger')
        return redirect(url_for('view_profile', username=user.username))
    
    success, message = current_user.send_friend_request(user)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'success' if success else 'error', 'message': message})
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('view_profile', username=user.username))

@app.route('/accept-friend-request/<int:user_id>', methods=['POST'])
@login_required
def accept_friend_request(user_id):
    user = User.query.get_or_404(user_id)
    
    if not current_user.has_received_friend_request(user):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'No friend request found from this user'})
        flash('No friend request found from this user', 'danger')
        return redirect(url_for('view_profile', username=user.username))
    
    # Find the pending friend request
    friend_request = FriendRequest.query.filter_by(
        sender_id=user.id,
        receiver_id=current_user.id,
        status='pending'
    ).first_or_404()
    
    success, message = current_user.accept_friend_request(friend_request)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'success' if success else 'error', 'message': message})
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('view_profile', username=user.username))

@app.route('/friend-request/<int:request_id>/<action>', methods=['POST'])
@login_required
def handle_friend_request(request_id, action):
    friend_request = FriendRequest.query.get_or_404(request_id)
    
    if friend_request.receiver_id != current_user.id:
        flash('You are not authorized to handle this request', 'danger')
        return redirect(url_for('friend_request_logs'))
    
    if action == 'accept':
        success, message = current_user.accept_friend_request(friend_request)
    elif action == 'reject':
        success, message = current_user.reject_friend_request(friend_request)
    else:
        flash('Invalid action', 'danger')
        return redirect(url_for('friend_request_logs'))
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('friend_request_logs'))

@app.route('/block/<int:user_id>')
@login_required
def block_user(user_id):
    user = User.query.get_or_404(user_id)
    success, message = current_user.block_user(user)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('view_profile', username=user.username))

@app.route('/unblock/<int:user_id>')
@login_required
def unblock_user(user_id):
    user = User.query.get_or_404(user_id)
    success, message = current_user.unblock_user(user)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('home'))

@app.route('/friend-request-logs')
@login_required
def friend_request_logs():
    logs = current_user.get_friend_request_logs()
    return render_template('friend_request_logs.html', logs=logs)

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/profiles')
@login_required
def profiles():
    search_query = request.args.get('search', '').strip()
    
    # Get users who have blocked the current user
    blocked_by_users = [block.blocker_id for block in Block.query.filter_by(blocked_id=current_user.id).all()]
    
    if search_query:
        users = User.query.filter(
            User.id != current_user.id,  # Exclude current user
            ~User.id.in_(blocked_by_users),  # Exclude users who blocked current user
            (User.username.ilike(f'%{search_query}%')) |
            (User.bio.ilike(f'%{search_query}%'))
        ).all()
    else:
        users = User.query.filter(
            User.id != current_user.id,  # Exclude current user
            ~User.id.in_(blocked_by_users)  # Exclude users who blocked current user
        ).all()
    
    # If it's an AJAX request, only return the profiles grid
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render_template('profiles_grid.html', users=users)
    
    return render_template('profiles.html', users=users)

@app.route('/add-friend/<int:user_id>', methods=['POST'])
@login_required
def add_friend(user_id):
    user = User.query.get_or_404(user_id)
    
    if user == current_user:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'You cannot add yourself as a friend'})
        flash('You cannot add yourself as a friend', 'danger')
        return redirect(url_for('view_profile', username=user.username))
    
    if not user.is_public_profile:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Cannot directly add a private profile as friend'})
        flash('Cannot directly add a private profile as friend', 'danger')
        return redirect(url_for('view_profile', username=user.username))
    
    if user in current_user.friends:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'error', 'message': 'Already friends with this user'})
        flash('Already friends with this user', 'danger')
        return redirect(url_for('view_profile', username=user.username))
    
    # Add both users to each other's friends list
    current_user.friends.append(user)
    user.friends.append(current_user)
    db.session.commit()
    
    message = f'Successfully added {user.username} as a friend'
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'status': 'success', 'message': message})
    
    flash(message, 'success')
    return redirect(url_for('view_profile', username=user.username))

@app.route('/friends')
@login_required
def friends_management():
    try:
        # Get all friends of the current user
        friends = current_user.friends.all()
        return render_template('friends.html', friends=friends)
    except Exception as e:
        app.logger.error(f"Error in friends_management: {str(e)}")
        flash('0 friends in your friends list', 'danger')
        return redirect(url_for('home'))

@app.route('/scan_qr', methods=['GET', 'POST'])
@login_required
def scan_qr():
    if request.method == 'POST':
        try:
            qr_data = request.form.get('qr_data')
            if not qr_data:
                return jsonify({'success': False, 'message': 'No QR code data received'})
            
            # Parse QR data (format: user_id:username)
            user_id, username = qr_data.split(':')
            user = User.query.get(int(user_id))
            
            if not user:
                return jsonify({'success': False, 'message': 'User not found'})
            
            if user == current_user:
                return jsonify({'success': False, 'message': 'Cannot add yourself as a friend'})
            
            if user in current_user.friends:
                return jsonify({'success': False, 'message': 'Already friends with this user'})
            
            # Send friend request
            success, message = current_user.send_friend_request(user)
            return jsonify({'success': success, 'message': message})
            
        except Exception as e:
            app.logger.error(f"Error processing QR code: {str(e)}")
            return jsonify({'success': False, 'message': 'Error processing QR code'})
    
    return jsonify({'success': False, 'message': 'Invalid request method'})

@app.route('/my_qr')
@login_required
def my_qr():
    qr_code = current_user.get_qr_code()
    return render_template('my_qr.html', qr_code=qr_code)

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = UnfilteredPost.query.get_or_404(post_id)
    
    # Check if the current user is the author of the post
    if post.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'You are not authorized to delete this post'})
    
    try:
        # Delete the media file if it exists
        if post.media_url:
            # Get the filename from the URL
            filename = post.media_url.split('/')[-1]
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Delete the file if it exists
            if os.path.exists(file_path):
                os.remove(file_path)
                
            # If it's a photo, also try to delete the compressed version
            if post.media_type == 'photo':
                compressed_path = os.path.join(app.config['UPLOAD_FOLDER'], 'compressed', filename)
                if os.path.exists(compressed_path):
                    os.remove(compressed_path)
        
        # Delete associated reactions and comments
        db.session.query(post_reactions).filter_by(post_id=post.id).delete()
        Comment.query.filter_by(post_id=post.id).delete()
        
        # Delete the post
        db.session.delete(post)
        db.session.commit()
        
        return jsonify({'status': 'success', 'message': 'Post deleted successfully'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Error deleting post: {str(e)}'})

@app.route('/post/<int:post_id>/archive', methods=['POST'])
@login_required
def archive_post(post_id):
    post = UnfilteredPost.query.get_or_404(post_id)
    
    # Check if the current user is the author of the post
    if post.user_id != current_user.id:
        return jsonify({'status': 'error', 'message': 'You are not authorized to archive this post'})
    
    try:
        # Toggle the archive status
        post.is_archived = not post.is_archived
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Post archived successfully' if post.is_archived else 'Post unarchived successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': f'Error archiving post: {str(e)}'})

@app.route('/send_vibe_ping', methods=['POST'])
@login_required
def send_vibe_ping():
    data = request.get_json()
    receiver_id = data.get('receiver_id')
    message = data.get('message')
    mood = data.get('mood', 'supportive')  # Get mood from request, default to 'supportive'
    is_anonymous = data.get('anonymous', False)  # Get anonymous flag from request
    
    if not receiver_id or not message:
        return jsonify({'error': 'Missing required fields'}), 400
    
    receiver = db.session.get(User, receiver_id)
    if not receiver:
        return jsonify({'error': 'Receiver not found'}), 404
    
    # Check if receiver is blocked or has blocked the sender
    if current_user.is_blocked_by(receiver) or current_user.has_blocked(receiver):
        return jsonify({'error': 'Cannot send vibe ping to this user'}), 403
    
    # Create the vibe ping
    vibe_ping = VibePing(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        message=message,
        mood=mood,
        is_anonymous=is_anonymous  # Set the anonymous flag
    )
    
    db.session.add(vibe_ping)
    db.session.commit()
    
    # Create a notification for the receiver
    notification = Notification(
        user_id=receiver_id,
        type='vibe_ping',
        content=f'You received {"an anonymous" if is_anonymous else "a"} vibe ping: "{message}"',
        reference_id=vibe_ping.id,
        reference_type='vibe_ping'
    )
    db.session.add(notification)
    db.session.commit()
    
    # Redirect to the receiver's profile with new_vibe_ping parameter
    return jsonify({
        'success': True, 
        'message': 'Vibe ping sent successfully',
        'redirect_url': url_for('view_profile', username=receiver.username, new_vibe_ping='true')
    })

@app.route('/vibe_pings', methods=['GET'])
@login_required
def get_vibe_pings():
    vibe_pings = VibePing.query.filter_by(receiver_id=current_user.id).order_by(VibePing.created_at.desc()).all()
    
    # Mark unread pings as read
    unread_pings = [ping for ping in vibe_pings if not ping.is_read]
    for ping in unread_pings:
        ping.is_read = True
    db.session.commit()
    
    return jsonify({
        'vibe_pings': [{
            'id': ping.id,
            'message': ping.message,
            'created_at': ping.created_at.isoformat(),
            'is_read': ping.is_read
        } for ping in vibe_pings]
    })

@app.route('/vibe_pings/unread_count', methods=['GET'])
@login_required
def get_unread_vibe_pings_count():
    count = VibePing.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    return jsonify({'count': count})

@app.route('/vibe_pings_page')
@login_required
def vibe_pings_page():
    return render_template('vibe_pings.html')

@app.route('/vibe_pings/friends', methods=['GET'])
@login_required
def get_friends_for_vibe_pings():
    try:
        friends = current_user.friends.all()
        return jsonify({
            'friends': [{
                'id': friend.id,
                'username': friend.username,
                'email': friend.email,
                'bio': friend.bio,
                'profile_picture_url': friend.profile_picture or url_for('static', filename='images/default_profile.png'),
                'status': 'Online'  # You can implement actual online status later
            } for friend in friends]
        })
    except Exception as e:
        app.logger.error(f"Error getting friends for vibe pings: {str(e)}")
        return jsonify({'friends': []})

@app.route('/vibe_pings/received', methods=['GET'])
@login_required
def get_received_vibes():
    try:
        # Get all vibe pings received by the current user
        vibe_pings = VibePing.query.filter_by(receiver_id=current_user.id).order_by(VibePing.created_at.desc()).all()
        
        # Mark unread pings as read
        unread_pings = [ping for ping in vibe_pings if not ping.is_read]
        for ping in unread_pings:
            ping.is_read = True
        db.session.commit()
        
        # Process and return the vibe pings
        return jsonify({
            'vibes': [{
                'id': ping.id,
                'sender': {
                    'id': ping.sender.id,
                    'username': ping.sender.username,
                    'profile_picture_url': ping.sender.profile_picture or url_for('static', filename='images/default_profile.png')
                },
                'message': ping.message,
                'mood': ping.mood or 'supportive',  # Default mood if not set
                'timestamp': ping.created_at.isoformat(),
                'is_read': ping.is_read,
                'is_anonymous': ping.is_anonymous  # Include anonymous status
            } for ping in vibe_pings]
        })
    except Exception as e:
        app.logger.error(f"Error getting received vibes: {str(e)}")
        return jsonify({'error': 'Failed to load vibes'}), 500

def create_test_profiles():
    test_profiles = [
        {
            'username': 'john_doe',
            'email': 'john@example.com',
            'bio': 'Music lover and coffee enthusiast',
            'is_public_profile': True
        },
        {
            'username': 'jane_smith',
            'email': 'jane@example.com',
            'bio': 'Photography and travel addict',
            'is_public_profile': True
        },
        {
            'username': 'mike_wilson',
            'email': 'mike@example.com',
            'bio': 'Tech geek and gamer',
            'is_public_profile': True
        },
        {
            'username': 'sarah_jones',
            'email': 'sarah@example.com',
            'bio': 'Art and design enthusiast',
            'is_public_profile': True
        },
        {
            'username': 'alex_brown',
            'email': 'alex@example.com',
            'bio': 'Fitness and health coach',
            'is_public_profile': True
        },
        {
            'username': 'emma_davis',
            'email': 'emma@example.com',
            'bio': 'Bookworm and writer',
            'is_public_profile': True
        },
        {
            'username': 'david_lee',
            'email': 'david@example.com',
            'bio': 'Foodie and chef',
            'is_public_profile': True
        },
        {
            'username': 'lisa_wong',
            'email': 'lisa@example.com',
            'bio': 'Yoga instructor and mindfulness coach',
            'is_public_profile': True
        },
        {
            'username': 'tom_hart',
            'email': 'tom@example.com',
            'bio': 'Adventure seeker and hiker',
            'is_public_profile': True
        },
        {
            'username': 'anna_kim',
            'email': 'anna@example.com',
            'bio': 'Fashion and style blogger',
            'is_public_profile': True
        }
    ]
    
    for profile in test_profiles:
        if not User.query.filter_by(username=profile['username']).first():
            user = User(
                username=profile['username'],
                email=profile['email'],
                bio=profile['bio'],
                is_public_profile=profile['is_public_profile']
            )
            user.set_password('password123')  # Set a default password for test accounts
            db.session.add(user)
    
    db.session.commit()

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('error.html', 
                          error_code=404, 
                          error_title="Page Not Found", 
                          error_message="The page you're looking for doesn't exist or is under construction."), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error.html', 
                          error_code=500, 
                          error_title="Server Error", 
                          error_message="Something went wrong on our end. Please try again later."), 500

@app.errorhandler(Exception)
def handle_exception(e):
    # Log the error for debugging
    app.logger.error(f"Unhandled exception: {str(e)}")
    return render_template('error.html', 
                          error_code=500, 
                          error_title="Unexpected Error", 
                          error_message="An unexpected error occurred. Please try again later."), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        create_test_profiles()  # Create test profiles when the app starts
    app.run(debug=True) 