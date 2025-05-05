from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from models import db, User, UnfilteredPost, Mood, Poll, Comment, PollVote, FriendRequest, Block
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import datetime
import os
from functools import wraps

# Create a Blueprint for API routes
api = Blueprint('api', __name__)

# JWT token required decorator
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Check if token is in headers
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({'message': 'Invalid token format'}), 401
        
        if not token:
            return jsonify({'message': 'Token is missing'}), 401
        
        try:
            # Decode token
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = User.query.get(data['user_id'])
        except:
            return jsonify({'message': 'Token is invalid'}), 401
        
        return f(current_user, *args, **kwargs)
    
    return decorated

# Authentication endpoints
@api.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    
    # Check if user already exists
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'message': 'Username already exists'}), 400
    
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'message': 'Email already exists'}), 400
    
    # Create new user
    hashed_password = generate_password_hash(data['password'])
    new_user = User(
        username=data['username'],
        email=data['email'],
        password=hashed_password,
        is_public_profile=data.get('is_public_profile', True)
    )
    
    db.session.add(new_user)
    db.session.commit()
    
    # Generate token
    token = jwt.encode({
        'user_id': new_user.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, current_app.config['SECRET_KEY'])
    
    return jsonify({
        'message': 'User created successfully',
        'token': token,
        'user': {
            'id': new_user.id,
            'username': new_user.username,
            'email': new_user.email,
            'is_public_profile': new_user.is_public_profile
        }
    }), 201

@api.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    
    # Find user
    user = User.query.filter_by(username=data['username']).first()
    
    if not user or not check_password_hash(user.password, data['password']):
        return jsonify({'message': 'Invalid username or password'}), 401
    
    # Generate token
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }, current_app.config['SECRET_KEY'])
    
    return jsonify({
        'message': 'Login successful',
        'token': token,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'is_public_profile': user.is_public_profile,
            'profile_picture': user.profile_picture
        }
    }), 200

# User endpoints
@api.route('/user/profile', methods=['GET'])
@token_required
def get_profile(current_user):
    return jsonify({
        'id': current_user.id,
        'username': current_user.username,
        'email': current_user.email,
        'bio': current_user.bio,
        'is_public_profile': current_user.is_public_profile,
        'profile_picture': current_user.profile_picture,
        'created_at': current_user.created_at.isoformat()
    }), 200

@api.route('/user/profile', methods=['PUT'])
@token_required
def update_profile(current_user):
    data = request.get_json()
    
    if 'username' in data:
        # Check if username is already taken
        existing_user = User.query.filter_by(username=data['username']).first()
        if existing_user and existing_user.id != current_user.id:
            return jsonify({'message': 'Username already exists'}), 400
        current_user.username = data['username']
    
    if 'email' in data:
        # Check if email is already taken
        existing_user = User.query.filter_by(email=data['email']).first()
        if existing_user and existing_user.id != current_user.id:
            return jsonify({'message': 'Email already exists'}), 400
        current_user.email = data['email']
    
    if 'bio' in data:
        current_user.bio = data['bio']
    
    if 'is_public_profile' in data:
        current_user.is_public_profile = data['is_public_profile']
    
    if 'password' in data and data['password']:
        current_user.password = generate_password_hash(data['password'])
    
    db.session.commit()
    
    return jsonify({'message': 'Profile updated successfully'}), 200

# Mood endpoints
@api.route('/moods', methods=['GET'])
@token_required
def get_moods(current_user):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    # Get moods from friends and public profiles
    moods = Mood.query.join(User).filter(
        (User.id.in_([friend.id for friend in current_user.friends])) |
        (User.is_public_profile == True)
    ).order_by(Mood.created_at.desc()).paginate(page=page, per_page=per_page)
    
    return jsonify({
        'moods': [{
            'id': mood.id,
            'emoji': mood.emoji,
            'caption': mood.caption,
            'created_at': mood.created_at.isoformat(),
            'user': {
                'id': mood.author.id,
                'username': mood.author.username,
                'profile_picture': mood.author.profile_picture
            }
        } for mood in moods.items],
        'total': moods.total,
        'pages': moods.pages,
        'current_page': moods.page
    }), 200

@api.route('/moods', methods=['POST'])
@token_required
def create_mood(current_user):
    data = request.get_json()
    
    new_mood = Mood(
        emoji=data['emoji'],
        caption=data.get('caption', ''),
        author=current_user
    )
    
    db.session.add(new_mood)
    db.session.commit()
    
    return jsonify({
        'message': 'Mood created successfully',
        'mood': {
            'id': new_mood.id,
            'emoji': new_mood.emoji,
            'caption': new_mood.caption,
            'created_at': new_mood.created_at.isoformat()
        }
    }), 201

# Post endpoints
@api.route('/posts', methods=['GET'])
@token_required
def get_posts(current_user):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    # Get posts from friends and public profiles
    posts = UnfilteredPost.query.join(User).filter(
        (User.id.in_([friend.id for friend in current_user.friends])) |
        (User.is_public_profile == True)
    ).order_by(UnfilteredPost.created_at.desc()).paginate(page=page, per_page=per_page)
    
    return jsonify({
        'posts': [{
            'id': post.id,
            'caption': post.caption,
            'media_url': post.media_url,
            'media_type': post.media_type,
            'created_at': post.created_at.isoformat(),
            'user': {
                'id': post.author.id,
                'username': post.author.username,
                'profile_picture': post.author.profile_picture
            }
        } for post in posts.items],
        'total': posts.total,
        'pages': posts.pages,
        'current_page': posts.page
    }), 200

@api.route('/posts', methods=['POST'])
@token_required
def create_post(current_user):
    # Handle file upload
    if 'media' not in request.files:
        return jsonify({'message': 'No media file provided'}), 400
    
    file = request.files['media']
    caption = request.form.get('caption', '')
    
    if file.filename == '':
        return jsonify({'message': 'No selected file'}), 400
    
    # Determine media type
    media_type = 'photo'
    if file.content_type.startswith('video'):
        media_type = 'video'
    
    # Save file
    filename = secure_filename(file.filename)
    unique_filename = f"{uuid.uuid4()}_{filename}"
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(file_path)
    
    # Create post
    new_post = UnfilteredPost(
        caption=caption,
        media_url=file_path,
        media_type=media_type,
        author=current_user
    )
    
    db.session.add(new_post)
    db.session.commit()
    
    return jsonify({
        'message': 'Post created successfully',
        'post': {
            'id': new_post.id,
            'caption': new_post.caption,
            'media_url': new_post.media_url,
            'media_type': new_post.media_type,
            'created_at': new_post.created_at.isoformat()
        }
    }), 201

# Poll endpoints
@api.route('/polls', methods=['GET'])
@token_required
def get_polls(current_user):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    # Get polls from friends and public profiles
    polls = Poll.query.join(User).filter(
        (User.id.in_([friend.id for friend in current_user.friends])) |
        (User.is_public_profile == True)
    ).order_by(Poll.created_at.desc()).paginate(page=page, per_page=per_page)
    
    return jsonify({
        'polls': [{
            'id': poll.id,
            'question': poll.question,
            'options': poll.options_list,
            'image_url': poll.image_url,
            'created_at': poll.created_at.isoformat(),
            'user': {
                'id': poll.author.id,
                'username': poll.author.username,
                'profile_picture': poll.author.profile_picture
            },
            'has_voted': any(vote.user_id == current_user.id for vote in poll.votes),
            'total_votes': sum(len(vote.options) for vote in poll.votes)
        } for poll in polls.items],
        'total': polls.total,
        'pages': polls.pages,
        'current_page': polls.page
    }), 200

@api.route('/polls', methods=['POST'])
@token_required
def create_poll(current_user):
    data = request.get_json()
    
    # Handle image upload if provided
    image_url = None
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '':
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4()}_{filename}"
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(file_path)
            image_url = file_path
    
    new_poll = Poll(
        question=data['question'],
        options=data['options'],
        image_url=image_url,
        author=current_user
    )
    
    db.session.add(new_poll)
    db.session.commit()
    
    return jsonify({
        'message': 'Poll created successfully',
        'poll': {
            'id': new_poll.id,
            'question': new_poll.question,
            'options': new_poll.options_list,
            'image_url': new_poll.image_url,
            'created_at': new_poll.created_at.isoformat()
        }
    }), 201

@api.route('/polls/<int:poll_id>/vote', methods=['POST'])
@token_required
def vote_poll(current_user, poll_id):
    poll = Poll.query.get_or_404(poll_id)
    data = request.get_json()
    
    # Check if user has already voted
    existing_vote = PollVote.query.filter_by(user_id=current_user.id, poll_id=poll_id).first()
    if existing_vote:
        # Update existing vote
        existing_vote.options = data['options']
    else:
        # Create new vote
        new_vote = PollVote(
            user_id=current_user.id,
            poll_id=poll_id,
            options=data['options']
        )
        db.session.add(new_vote)
    
    db.session.commit()
    
    return jsonify({'message': 'Vote recorded successfully'}), 200

# Friend endpoints
@api.route('/friends', methods=['GET'])
@token_required
def get_friends(current_user):
    return jsonify({
        'friends': [{
            'id': friend.id,
            'username': friend.username,
            'profile_picture': friend.profile_picture,
            'bio': friend.bio
        } for friend in current_user.friends]
    }), 200

@api.route('/friends/requests', methods=['GET'])
@token_required
def get_friend_requests(current_user):
    received_requests = FriendRequest.query.filter_by(receiver=current_user, status='pending').all()
    sent_requests = FriendRequest.query.filter_by(sender=current_user, status='pending').all()
    
    return jsonify({
        'received_requests': [{
            'id': request.id,
            'sender': {
                'id': request.sender.id,
                'username': request.sender.username,
                'profile_picture': request.sender.profile_picture
            },
            'created_at': request.created_at.isoformat()
        } for request in received_requests],
        'sent_requests': [{
            'id': request.id,
            'receiver': {
                'id': request.receiver.id,
                'username': request.receiver.username,
                'profile_picture': request.receiver.profile_picture
            },
            'created_at': request.created_at.isoformat()
        } for request in sent_requests]
    }), 200

@api.route('/friends/request/<int:user_id>', methods=['POST'])
@token_required
def send_friend_request(current_user, user_id):
    if user_id == current_user.id:
        return jsonify({'message': 'Cannot send friend request to yourself'}), 400
    
    user = User.query.get_or_404(user_id)
    
    # Check if already friends
    if user in current_user.friends:
        return jsonify({'message': 'Already friends with this user'}), 400
    
    # Check if request already exists
    existing_request = FriendRequest.query.filter(
        ((FriendRequest.sender_id == current_user.id) & (FriendRequest.receiver_id == user_id)) |
        ((FriendRequest.sender_id == user_id) & (FriendRequest.receiver_id == current_user.id))
    ).first()
    
    if existing_request:
        return jsonify({'message': 'Friend request already exists'}), 400
    
    # Create new request
    new_request = FriendRequest(sender=current_user, receiver=user)
    db.session.add(new_request)
    db.session.commit()
    
    return jsonify({'message': 'Friend request sent successfully'}), 201

@api.route('/friends/request/<int:request_id>/<action>', methods=['POST'])
@token_required
def handle_friend_request(current_user, request_id, action):
    friend_request = FriendRequest.query.get_or_404(request_id)
    
    # Verify the current user is the receiver
    if friend_request.receiver_id != current_user.id:
        return jsonify({'message': 'Unauthorized'}), 403
    
    if action == 'accept':
        friend_request.status = 'accepted'
        current_user.friends.append(friend_request.sender)
        friend_request.sender.friends.append(current_user)
    elif action == 'reject':
        friend_request.status = 'rejected'
    else:
        return jsonify({'message': 'Invalid action'}), 400
    
    db.session.commit()
    
    return jsonify({'message': f'Friend request {action}ed successfully'}), 200

# Profile endpoints
@api.route('/profiles', methods=['GET'])
@token_required
def get_profiles(current_user):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')
    
    # Get users who have blocked the current user
    blocked_by_users = [block.blocker_id for block in Block.query.filter_by(blocked_id=current_user.id).all()]
    
    # Query users based on search
    query = User.query.filter(
        User.id != current_user.id,
        ~User.id.in_(blocked_by_users)  # Exclude users who blocked current user
    )
    
    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) |
            (User.bio.ilike(f'%{search}%'))
        )
    
    users = query.paginate(page=page, per_page=per_page)
    
    return jsonify({
        'users': [{
            'id': user.id,
            'username': user.username,
            'profile_picture': user.profile_picture,
            'bio': user.bio,
            'is_public_profile': user.is_public_profile,
            'is_friend': user in current_user.friends,
            'friend_request_sent': FriendRequest.query.filter_by(
                sender=current_user, receiver=user, status='pending'
            ).first() is not None,
            'friend_request_received': FriendRequest.query.filter_by(
                sender=user, receiver=current_user, status='pending'
            ).first() is not None
        } for user in users.items],
        'total': users.total,
        'pages': users.pages,
        'current_page': users.page
    }), 200

@api.route('/profile/<username>', methods=['GET'])
@token_required
def get_profile_by_username(current_user, username):
    profile_user = User.query.filter_by(username=username).first_or_404()
    
    # Check if the profile is accessible
    if not profile_user.is_public_profile and not current_user.is_friend(profile_user) and profile_user.id != current_user.id:
        return jsonify({'message': 'This profile is private'}), 403
    
    # Get user's content
    user_moods = profile_user.moods.order_by(Mood.created_at.desc()).limit(4).all()
    user_posts = profile_user.posts.order_by(UnfilteredPost.created_at.desc()).limit(4).all()
    user_polls = profile_user.polls.order_by(Poll.created_at.desc()).limit(4).all()
    
    # Check if current user is friends with profile user
    is_friend = current_user.is_friend(profile_user)
    
    return jsonify({
        'user': {
            'id': profile_user.id,
            'username': profile_user.username,
            'email': profile_user.email,
            'bio': profile_user.bio,
            'is_public_profile': profile_user.is_public_profile,
            'profile_picture': profile_user.profile_picture,
            'created_at': profile_user.created_at.isoformat()
        },
        'is_friend': is_friend,
        'moods': [{
            'id': mood.id,
            'emoji': mood.emoji,
            'caption': mood.caption,
            'created_at': mood.created_at.isoformat()
        } for mood in user_moods],
        'posts': [{
            'id': post.id,
            'caption': post.caption,
            'media_url': post.media_url,
            'media_type': post.media_type,
            'created_at': post.created_at.isoformat()
        } for post in user_posts],
        'polls': [{
            'id': poll.id,
            'question': poll.question,
            'options': poll.options_list,
            'image_url': poll.image_url,
            'created_at': poll.created_at.isoformat(),
            'has_voted': any(vote.user_id == current_user.id for vote in poll.votes),
            'total_votes': sum(len(vote.options) for vote in poll.votes)
        } for poll in user_polls]
    }), 200

@api.route('/stats', methods=['GET'])
@token_required
def get_stats(current_user):
    return jsonify({
        'moods_count': Mood.query.filter_by(author=current_user).count(),
        'posts_count': UnfilteredPost.query.filter_by(author=current_user).count(),
        'polls_count': Poll.query.filter_by(author=current_user).count(),
        'friends_count': current_user.friends.count()
    }), 200 