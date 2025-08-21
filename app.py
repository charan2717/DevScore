from flask import Flask, render_template, redirect, url_for, session, flash, request, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import os
from urllib.parse import quote_plus
import zipfile
import tempfile
from werkzeug.utils import secure_filename

# -------------------------
# SETUP
# -------------------------
load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev_secret')

# MongoDB Atlas Connection
username = "charan"
password = quote_plus("BxN7G6sqk9dhECa6")
cluster_url = "cluster0.ysxk5ry.mongodb.net"
database_name = "scorer"
MONGO_URI = f"mongodb+srv://{username}:{password}@{cluster_url}/{database_name}?retryWrites=true&w=majority&appName=Cluster0"

client = MongoClient(MONGO_URI)
db = client[database_name]
users_col = db["users"]
profiles_col = db["profiles"]
projects_col = db["projects"]

# Upload settings
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"zip"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# -------------------------
# PROJECT SCORING
# -------------------------
def score_project(zip_path):
    score = 0
    categories = {}
    with tempfile.TemporaryDirectory() as temp_dir:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        file_list = []
        for root, dirs, files in os.walk(temp_dir):
            for f in files:
                file_list.append(os.path.join(root, f))

        # Code Diversity
        extensions = set([os.path.splitext(f)[1] for f in file_list])
        if len(extensions) >= 3: categories["Code Diversity"] = 20
        elif len(extensions) == 2: categories["Code Diversity"] = 15
        elif len(extensions) == 1: categories["Code Diversity"] = 10
        else: categories["Code Diversity"] = 0

        # Documentation
        categories["Documentation"] = 20 if any("readme" in f.lower() for f in file_list) else 0

        # File Structure
        categories["File Structure"] = 15 if any(os.path.isdir(os.path.join(temp_dir, d)) for d in os.listdir(temp_dir)) else 5

        # Test Coverage
        categories["Tests"] = 20 if any("test" in f.lower() for f in file_list) else 0

        # Size & Complexity
        total_files = len(file_list)
        if total_files < 5: categories["Complexity"] = 5
        elif total_files < 20: categories["Complexity"] = 15
        else: categories["Complexity"] = 10

        score = sum(categories.values())
    return score, categories

# -------------------------
# SAVE & EXTRACT ZIP
# -------------------------
def save_and_extract_zip(file, user_id):
    filename = secure_filename(file.filename)
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], user_id)
    os.makedirs(user_folder, exist_ok=True)
    project_folder = os.path.join(user_folder, os.path.splitext(filename)[0])
    os.makedirs(project_folder, exist_ok=True)
    filepath = os.path.join(user_folder, filename)
    file.save(filepath)
    with zipfile.ZipFile(filepath, 'r') as zip_ref:
        zip_ref.extractall(project_folder)
    return project_folder, filename

# -------------------------
# ROUTES
# -------------------------
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return render_template('index.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method=='POST':
        email = request.form['email'].lower()
        password = request.form['password']
        if users_col.find_one({'email': email}):
            flash('User already exists')
        else:
            hashed = generate_password_hash(password)
            users_col.insert_one({'email': email, 'password': hashed, 'profile_completed': False, 'terms_accepted': False})
            flash('Signup successful. Please login.')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('home'))
    if request.method=='POST':
        email = request.form['email'].lower()
        password = request.form['password']
        user = users_col.find_one({'email': email})
        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            return redirect(url_for('home'))
        flash('Invalid Credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/profile', methods=['GET','POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    profile = profiles_col.find_one({"user_id": session['user_id']})

    if request.method == 'POST':
        name = request.form['name']
        age = request.form['age']
        bio = request.form['bio']

        profiles_col.update_one(
            {"user_id": session['user_id']},
            {"$set": {"name": name, "age": age, "bio": bio}},
            upsert=True
        )

        users_col.update_one(
            {"_id": ObjectId(session['user_id'])},
            {"$set": {"profile_completed": True}}
        )

        # Reload profile after update
        profile = profiles_col.find_one({"user_id": session['user_id']})

        # Redirect to profile display page
        return redirect(url_for('profile'))

    # Check if profile exists and show filled info
    return render_template('profile.html', profile=profile)


@app.route('/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'message': 'Not logged in'}), 401

    data = request.get_json()
    display_name = data.get('displayName', '')
    bio = data.get('bio', '')

    profiles_col.update_one(
        {'user_id': session['user_id']},
        {'$set': {'name': display_name, 'bio': bio}},
        upsert=True
    )
    return jsonify({'message': 'Profile updated successfully'})

@app.route('/terms', methods=['GET','POST'])
def terms():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method=='POST':
        users_col.update_one({"_id": ObjectId(session['user_id'])},{"$set":{"terms_accepted": True}})
        return redirect(url_for('home'))
    return render_template('terms.html')

@app.route('/settings', methods=['GET','POST'])
def settings():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = users_col.find_one({"_id": ObjectId(session['user_id'])})
    if request.method=='POST':
        users_col.update_one({"_id": ObjectId(session['user_id'])},{"$set":{"settings_completed": True}})
        flash('Settings updated successfully.')
        return redirect(url_for('home'))
    return render_template('settings.html', user=user)

@app.route('/home')
@app.route('/homepage')
def home():
    if 'user_id' not in session: return redirect(url_for('login'))
    user = users_col.find_one({"_id": ObjectId(session['user_id'])})
    profile = profiles_col.find_one({"user_id": session['user_id']})
    if not user: return redirect(url_for('login'))
    if not user.get("profile_completed", False): return redirect(url_for('profile'))
    if not user.get("terms_accepted", False): return redirect(url_for('terms'))
    username = profile['name'] if profile and 'name' in profile else 'User'
    last_project = projects_col.find_one({"user_id": session['user_id']}, sort=[("_id", -1)])
    return render_template('homepage.html', user=user, username=username, last_project=last_project)

@app.route('/update_password', methods=['POST'])
def update_password():
    if 'user_id' not in session:
        return jsonify({'message': 'Not logged in'}), 401

    data = request.get_json()
    current = data['currentPassword']
    new_pass = data['newPassword']

    user = users_col.find_one({'_id': ObjectId(session['user_id'])})
    if not user or not check_password_hash(user['password'], current):
        return jsonify({'message': 'Current password incorrect'}), 400

    hashed = generate_password_hash(new_pass)
    users_col.update_one({'_id': ObjectId(session['user_id'])}, {'$set': {'password': hashed}})
    return jsonify({'message': 'Password updated successfully'})

# -------------------------
# UPLOAD PROJECT
# -------------------------
@app.route('/upload_project', methods=['POST'])
def upload_project():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if 'file' not in request.files:
        flash("No file selected")
        return redirect(url_for('home'))

    file = request.files['file']
    if file.filename == "":
        flash("No file selected")
        return redirect(url_for('home'))

    if file and allowed_file(file.filename):
        # Generate secure filename
        filename = secure_filename(file.filename)

        # Each user gets a separate folder
        user_folder = os.path.join(app.config['UPLOAD_FOLDER'], session['user_id'])
        os.makedirs(user_folder, exist_ok=True)

        # Full path to save zip
        zip_path = os.path.join(user_folder, filename)
        file.save(zip_path)

        # ---- Score the zip BEFORE extracting ----
        final_score, categories = score_project(zip_path)

        # ---- Extract the zip for browsing later ----
        project_folder = os.path.join(user_folder, os.path.splitext(filename)[0])
        os.makedirs(project_folder, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(project_folder)

        # Save project info and score to MongoDB
        projects_col.insert_one({
            "user_id": session['user_id'],
            "filename": filename,
            "folder": project_folder,   # path where files are extracted
            "score": final_score,
            "categories": categories
        })

        flash(f"Project uploaded! Total Score: {final_score}")
        return redirect(url_for('home'))
    else:
        flash("Only .zip files are allowed")
        return redirect(url_for('home'))


# -------------------------
# PROJECT BROWSING
# -------------------------
@app.route('/projects')
def projects():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_folder = os.path.join(app.config['UPLOAD_FOLDER'], session['user_id'])
    projects_list = os.listdir(user_folder) if os.path.exists(user_folder) else []
    return render_template('projects.html', projects=projects_list)

@app.route('/projects/<project_name>')
def view_project(project_name):
    if 'user_id' not in session: return redirect(url_for('login'))
    project_folder = os.path.join(app.config['UPLOAD_FOLDER'], session['user_id'], project_name)
    files = []
    for root, dirs, filenames in os.walk(project_folder):
        for f in filenames:
            rel_path = os.path.relpath(os.path.join(root,f), project_folder)
            files.append(rel_path)
    return render_template('project_files.html', project_name=project_name, files=files)

@app.route('/projects/<project_name>/file/<path:filename>')
def view_file(project_name, filename):
    if 'user_id' not in session: return redirect(url_for('login'))
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], session['user_id'], project_name, filename)
    if not os.path.exists(file_path): return "File not found", 404
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        code_content = f.read()
    return render_template('view_file.html', filename=filename, code=code_content)

# -------------------------
if __name__ == '__main__':
    app.run(debug=True)
