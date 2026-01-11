from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSON

db = SQLAlchemy()

class Video(db.Model):
    __tablename__ = 'videos'
    
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    duration = db.Column(db.Float)
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    edl = db.Column(JSON)  # Edit Decision List: [{"start": 0, "end": 10}, ...]
    final_video_path = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    frame_batches = db.relationship('FrameBatch', backref='video', cascade='all, delete-orphan')
    commentary = db.relationship('Commentary', backref='video', uselist=False, cascade='all, delete-orphan')

class FrameBatch(db.Model):
    __tablename__ = 'frame_batches'
    
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    batch_number = db.Column(db.Integer, nullable=False)
    frame_paths = db.Column(JSON)  # List of frame file paths
    timestamps = db.Column(JSON)   # List of timestamps
    
    # Gemini Flash response
    analysis_response = db.Column(JSON)
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed, failed
    error_message = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Commentary(db.Model):
    __tablename__ = 'commentaries'
    
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    
    # Merged frame analysis
    merged_events = db.Column(JSON)
    
    # Final commentary
    commentary_text = db.Column(db.Text) # Raw text with timestamps
    clean_commentary_text = db.Column(db.Text) # Text without timestamps
    structured_commentary = db.Column(JSON) # List of {timestamp, text, audio_path}
    audio_path = db.Column(db.String(255)) # Path to mixed audio (optional/legacy)
    
    status = db.Column(db.String(50), default='pending')
    error_message = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
