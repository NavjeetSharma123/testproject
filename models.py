from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import os
from flask import url_for

db = SQLAlchemy()

# Association tables for many-to-many relationships
friends = db.Table('friends',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('friend_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

post_reactions = db.Table('post_reactions',
    db.Column('post_id', db.Integer, db.ForeignKey('unfiltered_post.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20), unique=True)
    password_hash = db.Column(db.String(128))
    bio = db.Column(db.Text)
    profile_picture = db.Column(db.String(255))
    mood_palette = db.Column(db.String(255))  # JSON string of selected colors
    invite_code = db.Column(db.String(20), unique=True)
    referred_by = db.Column(db.String(20), db.ForeignKey('user.invite_code'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_verified = db.Column(db.Boolean, default=False)
    is_public_profile = db.Column(db.Boolean, default=False)  # False = private (friends only), True = public
    reset_token = db.Column(db.String(100), unique=True)
    reset_token_expiry = db.Column(db.DateTime)
    qr_code = db.Column(db.Text)  # Base64 encoded QR code image
    date_of_birth = db.Column(db.Date)  # Added date_of_birth field
    
    # Relationships
    friends = db.relationship('User', secondary=friends,
                            primaryjoin=(friends.c.user_id == id),
                            secondaryjoin=(friends.c.friend_id == id),
                            backref=db.backref('friend_of', lazy='dynamic'),
                            lazy='dynamic')
    
    # Content relationships
    posts = db.relationship('UnfilteredPost', backref='author', lazy='dynamic')
    moods = db.relationship('Mood', backref='author', lazy='dynamic')
    polls = db.relationship('Poll', backref='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Add methods for friend management
    def send_friend_request(self, user):
        if user == self:
            return False, "You cannot send a friend request to yourself"
        
        if user in self.friends:
            return False, "You are already friends with this user"
        
        existing_request = FriendRequest.query.filter_by(
            sender_id=self.id, receiver_id=user.id, status='pending'
        ).first()
        
        if existing_request:
            return False, "Friend request already sent"
        
        new_request = FriendRequest(sender_id=self.id, receiver_id=user.id)
        db.session.add(new_request)
        
        # Log the friend request creation
        log_entry = FriendRequestLog(
            friend_request=new_request,
            action='created',
            modified_by_id=self.id,
            new_status='pending',
            notes=f"Friend request sent from {self.username} to {user.username}"
        )
        db.session.add(log_entry)
        
        db.session.commit()
        return True, "Friend request sent"
    
    def accept_friend_request(self, request):
        if request.receiver_id != self.id:
            return False, "This request is not for you"
        
        if request.status != 'pending':
            return False, "This request has already been processed"
        
        previous_status = request.status
        request.status = 'accepted'
        self.friends.append(request.sender)
        request.sender.friends.append(self)
        
        # Log the friend request acceptance
        log_entry = FriendRequestLog(
            friend_request=request,
            action='accepted',
            modified_by_id=self.id,
            previous_status=previous_status,
            new_status='accepted',
            notes=f"Friend request from {request.sender.username} accepted by {self.username}"
        )
        db.session.add(log_entry)
        
        db.session.commit()
        return True, "Friend request accepted"
    
    def reject_friend_request(self, request):
        if request.receiver_id != self.id:
            return False, "This request is not for you"
        
        if request.status != 'pending':
            return False, "This request has already been processed"
        
        previous_status = request.status
        request.status = 'rejected'
        
        # Log the friend request rejection
        log_entry = FriendRequestLog(
            friend_request=request,
            action='rejected',
            modified_by_id=self.id,
            previous_status=previous_status,
            new_status='rejected',
            notes=f"Friend request from {request.sender.username} rejected by {self.username}"
        )
        db.session.add(log_entry)
        
        db.session.commit()
        return True, "Friend request rejected"
    
    def block_user(self, user):
        if user == self:
            return False, "You cannot block yourself"
        
        if user in self.friends:
            self.friends.remove(user)
            user.friends.remove(self)
        
        existing_block = Block.query.filter_by(
            blocker_id=self.id, blocked_id=user.id
        ).first()
        
        if existing_block:
            return False, "User is already blocked"
        
        new_block = Block(blocker_id=self.id, blocked_id=user.id)
        db.session.add(new_block)
        db.session.commit()
        return True, "User blocked"
    
    def unblock_user(self, user):
        block = Block.query.filter_by(
            blocker_id=self.id, blocked_id=user.id
        ).first()
        
        if not block:
            return False, "User is not blocked"
        
        db.session.delete(block)
        db.session.commit()
        return True, "User unblocked"
    
    def report_user(self, user, reason, details=None):
        if user == self:
            return False, "You cannot report yourself"
        
        new_report = Report(
            reporter_id=self.id,
            reported_id=user.id,
            reason=reason,
            details=details
        )
        db.session.add(new_report)
        db.session.commit()
        return True, "User reported"
    
    def generate_qr_code(self):
        """Generate a QR code for the user containing their ID and username"""
        try:
            import qrcode
            import io
            import base64
            
            # Create QR code data (user ID and username)
            qr_data = f"{self.id}:{self.username}"
            
            # Generate QR code
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            # Create image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Convert to base64
            buffered = io.BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            
            # Save to database
            self.qr_code = img_str
            db.session.commit()
            
            return img_str
            
        except Exception as e:
            app.logger.error(f"Error generating QR code: {str(e)}")
            return None
    
    def get_qr_code(self):
        """Get the user's QR code, generating it if it doesn't exist"""
        if not self.qr_code:
            return self.generate_qr_code()
        return self.qr_code
    
    def get_pending_friend_requests(self):
        return FriendRequest.query.filter_by(receiver_id=self.id, status='pending').all()
    
    def get_friend_request_logs(self, limit=50):
        """Get logs of friend requests related to this user (sent or received)"""
        sent_requests = FriendRequest.query.filter_by(sender_id=self.id).all()
        received_requests = FriendRequest.query.filter_by(receiver_id=self.id).all()
        
        request_ids = [req.id for req in sent_requests + received_requests]
        
        return FriendRequestLog.query.filter(
            FriendRequestLog.friend_request_id.in_(request_ids)
        ).order_by(FriendRequestLog.created_at.desc()).limit(limit).all()
    
    def is_blocked_by(self, user):
        return Block.query.filter_by(
            blocker_id=user.id, blocked_id=self.id
        ).first() is not None
    
    def has_blocked(self, user):
        return Block.query.filter_by(
            blocker_id=self.id, blocked_id=user.id
        ).first() is not None
    
    def can_interact_with(self, user):
        return not self.is_blocked_by(user) and not self.has_blocked(user)
    
    def is_friend(self, user):
        """Check if the user is friends with another user."""
        return user in self.friends
    
    def has_sent_friend_request(self, user):
        """Check if the user has sent a friend request to another user."""
        return FriendRequest.query.filter_by(
            sender_id=self.id,
            receiver_id=user.id,
            status='pending'
        ).first() is not None
    
    def has_received_friend_request(self, user):
        """Check if the user has received a friend request from another user."""
        return FriendRequest.query.filter_by(
            sender_id=user.id,
            receiver_id=self.id,
            status='pending'
        ).first() is not None

class UnfilteredPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    media_url = db.Column(db.String(255), nullable=False)
    media_type = db.Column(db.String(10), nullable=False)  # 'photo' or 'video'
    caption = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_public = db.Column(db.Boolean, default=False)
    allow_comments = db.Column(db.Boolean, default=True)
    is_one_shot = db.Column(db.Boolean, default=True)  # Indicates if this is a one-shot post
    is_archived = db.Column(db.Boolean, default=False)  # Indicates if the post is archived
    recording_duration = db.Column(db.Integer)  # Duration in seconds for videos
    location = db.Column(db.String(255))  # Optional location data
    emoji_reactions = db.Column(db.String(255))  # JSON string of emoji reactions
    
    # Relationships
    reactions = db.relationship('User', secondary=post_reactions, lazy='dynamic')
    comments = db.relationship('Comment', backref='post', lazy='dynamic')
    
    @property
    def display_media_url(self):
        """Returns the compressed version of the image URL if available, otherwise returns the original media URL"""
        if self.media_type == 'photo':
            # Get the filename from the media_url
            filename = os.path.basename(self.media_url)
            # Construct the path to the compressed version
            compressed_path = os.path.join('static', 'uploads', 'compressed', filename)
            # Check if the compressed version exists
            if os.path.exists(compressed_path):
                # Return the URL for the compressed version
                return url_for('static', filename=f'uploads/compressed/{filename}')
        # Return the original media URL if no compressed version exists or if it's not a photo
        return self.media_url
    
    @property
    def options_list(self):
        """For compatibility with the home template"""
        return []

class Mood(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    color_gradient = db.Column(db.String(255))  # JSON string of gradient colors
    caption = db.Column(db.Text)
    song_url = db.Column(db.String(255))
    photo_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    reactions = db.relationship('MoodReaction', backref='mood', lazy='dynamic')

class MoodReaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mood_id = db.Column(db.Integer, db.ForeignKey('mood.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reaction_type = db.Column(db.String(50), nullable=False)  # 'mirror', 'emoji', etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Poll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    question = db.Column(db.String(255), nullable=False)
    options = db.Column(db.String(1000), nullable=False)  # JSON string of options
    image_url = db.Column(db.String(255))  # URL to the poll image
    is_anonymous = db.Column(db.Boolean, default=False)
    is_public = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ends_at = db.Column(db.DateTime)
    
    # Relationships
    votes = db.relationship('PollVote', backref='poll', lazy='dynamic')
    comments = db.relationship('Comment', backref='poll', lazy='dynamic')
    
    @property
    def options_list(self):
        """Convert JSON string to list for template rendering"""
        import json
        try:
            return json.loads(self.options)
        except:
            return []

class PollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    option_index = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Polymorphic relationships
    post_id = db.Column(db.Integer, db.ForeignKey('unfiltered_post.id'))
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'))

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'mood', 'poll', 'friend', etc.
    content = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Reference to the related content
    reference_id = db.Column(db.Integer)  # ID of the related content (post, mood, poll, etc.)
    reference_type = db.Column(db.String(50))  # Type of the referenced content

class InviteCode(db.Model):
    code = db.Column(db.String(20), primary_key=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)
    max_uses = db.Column(db.Integer)
    current_uses = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_friend_requests')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_friend_requests')
    
    def __repr__(self):
        return f'<FriendRequest {self.sender.username} -> {self.receiver.username}>'

class FriendRequestLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    friend_request_id = db.Column(db.Integer, db.ForeignKey('friend_request.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # created, accepted, rejected, modified
    modified_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    previous_status = db.Column(db.String(20))  # For tracking status changes
    new_status = db.Column(db.String(20))  # For tracking status changes
    notes = db.Column(db.Text)  # Additional information about the action
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    friend_request = db.relationship('FriendRequest', backref='logs')
    modified_by = db.relationship('User', backref='friend_request_modifications')
    
    def __repr__(self):
        return f'<FriendRequestLog {self.friend_request.sender.username} -> {self.friend_request.receiver.username}: {self.action}>'

class Block(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    blocker = db.relationship('User', foreign_keys=[blocker_id], backref='blocked_users')
    blocked = db.relationship('User', foreign_keys=[blocked_id], backref='blocked_by_users')
    
    def __repr__(self):
        return f'<Block {self.blocker.username} -> {self.blocked.username}>'

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reported_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    details = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, reviewed, dismissed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    reporter = db.relationship('User', foreign_keys=[reporter_id], backref='reports_made')
    reported = db.relationship('User', foreign_keys=[reported_id], backref='reports_received')
    
    def __repr__(self):
        return f'<Report {self.reporter.username} -> {self.reported.username}>'

class VibePing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    mood = db.Column(db.String(50), nullable=True)  # Add mood field
    is_anonymous = db.Column(db.Boolean, default=False)  # Add anonymous flag
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_vibe_pings')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_vibe_pings')
    
    def __repr__(self):
        return f'<VibePing {self.id}: {self.message}>' 