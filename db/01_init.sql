-- Create videos table
CREATE TABLE IF NOT EXISTS videos (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    duration FLOAT,
    status VARCHAR(50) DEFAULT 'pending',
    deck_description TEXT,
    gcs_input_uri VARCHAR(255),
    gcs_output_uri VARCHAR(255),
    edl JSON,
    final_video_path VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create frame_batches table
CREATE TABLE IF NOT EXISTS frame_batches (
    id SERIAL PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    batch_number INTEGER NOT NULL,
    frame_paths JSON,
    timestamps JSON,
    analysis_response JSON,
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create commentaries table
CREATE TABLE IF NOT EXISTS commentaries (
    id SERIAL PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    merged_events JSON,
    commentary_text TEXT,
    clean_commentary_text TEXT,
    structured_commentary JSON,
    audio_path VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
