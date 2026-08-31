# Contributing to DMIS

Welcome to the Department Monitoring & Information System! We appreciate your interest in contributing to this project. This guide will help you get started.

## Setting Up Locally

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd DMIS
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables:**
   - Create a `.env` file in the root directory.
   - You can request the Firebase credentials from the repository maintainer or set up your own Firebase Realtime Database for testing.
   - Example `.env` format:
     ```env
     FLASK_SECRET_KEY=your_secret_key_here
     FIREBASE_API_KEY=your_api_key_here
     FIREBASE_AUTH_DOMAIN=your_project.firebaseapp.com
     FIREBASE_DATABASE_URL=https://your_project-default-rtdb.firebaseio.com
     FIREBASE_STORAGE_BUCKET=your_project.appspot.com
     ```

5. **Run the application:**
   ```bash
   flask run
   ```

## How to Contribute
- Check the **Issues** tab for tasks to work on.
- Fork the repository and create your feature branch: `git checkout -b feature-name`.
- Test your changes thoroughly.
- Submit a Pull Request with a clear description of the problem you solved or the feature you added.
