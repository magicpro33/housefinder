================================================================================
  HOUSE FINDER APP — Streamlit Web Version
================================================================================

Web version of House Finder: search homes by US zip code, house age, and
estimated value. Results appear in a table and on an interactive map.

Project folder:
  C:\Users\magic\projects\house finder app

Created by AIupscale — https://aiupscalellc.netlify.app/


--------------------------------------------------------------------------------
  INSTALL (FIRST TIME)
--------------------------------------------------------------------------------

  1. Double-click:  install.bat
  2. Copy .env.example to .env
  3. Add your RentCast API key:
       RENTCAST_API_KEY=your_key_here
     Free key: https://app.rentcast.io/app/api


--------------------------------------------------------------------------------
  RUN THE APP
--------------------------------------------------------------------------------

  Double-click:  run_app.bat

  Or from PowerShell in this folder:

    .venv\Scripts\streamlit run app.py

  Your browser opens to http://localhost:8501


--------------------------------------------------------------------------------
  FEATURES (same as desktop House Finder)
--------------------------------------------------------------------------------

  - Zip code search with age range (20–100 years) and value filters
  - Demo mode (sample homes, no API key) or RentCast live data
  - Enter API key in the sidebar OR Streamlit Secrets OR local .env
  - Local cache per zip (data\cache\) when running on your PC
  - Monthly API request counter (data\api_usage.json)
  - Force refresh option in sidebar (ignore cache)
  - Download results as .txt file
  - Interactive map with markers (OpenStreetMap via Folium)


--------------------------------------------------------------------------------
  FILE LAYOUT
--------------------------------------------------------------------------------

  house finder app\
    app.py              Streamlit web application
    run_app.bat         Start the local web server
    install.bat         Install Python dependencies
    requirements.txt
    .env                Your API key (create from .env.example)
    assets\             Logo and images
    data\               API usage + zip cache (auto-created)
    house_finder\       Search, filters, RentCast client (shared logic)


--------------------------------------------------------------------------------
  DEPLOY ON GITHUB + STREAMLIT CLOUD
--------------------------------------------------------------------------------

  1. CREATE A GITHUB REPO
     - Go to https://github.com/new
     - Name it e.g. house-finder-app
     - Do not add a README if you are pushing an existing folder

  2. PUSH THIS FOLDER (from PowerShell)

       cd "C:\Users\magic\projects\house finder app"
       git init
       git add .
       git commit -m "Initial House Finder Streamlit app"
       git branch -M main
       git remote add origin https://github.com/YOUR_USERNAME/house-finder-app.git
       git push -u origin main

     Important: .gitignore excludes .env, .venv, and data/ — never commit
     your RentCast API key.

  3. DEPLOY ON STREAMLIT CLOUD
     - Go to https://share.streamlit.io/
     - Sign in with GitHub
     - Click "Create app"
     - Repository: YOUR_USERNAME/house-finder-app
     - Branch: main
     - Main file path: app.py
     - Click "Advanced settings" → Python 3.10 or 3.11 if needed
     - Deploy

  4. ADD SECRETS (optional if users enter key in the app sidebar)
     - Open your app on Streamlit Cloud → Manage app → Settings → Secrets
     - Paste (with your real key) to pre-fill for all visitors:

         RENTCAST_API_KEY = "your_actual_key_here"
         RENTCAST_MONTHLY_LIMIT = "50"

     - Or leave secrets empty and let each user paste their own key in the sidebar
     - Save — the app will reboot automatically

  5. YOUR PUBLIC URL
     Streamlit gives you a URL like:
       https://house-finder-app-xxxxx.streamlit.app

  NOTES FOR CLOUD HOSTING
  -----------------------
  - Cache (data/cache) and API counters reset when the app restarts or
    redeploys — Streamlit Cloud does not keep local disk between sessions.
  - Each visitor shares the same deployed instance; API usage counts toward
    your RentCast key for all users of the public app.
  - For a private app, use Streamlit Cloud workspace settings or keep it
    unlisted and share the URL only with people you trust.
  - Logo and assets in assets/ are included in the repo and deploy fine.


--------------------------------------------------------------------------------
  DEPLOY ONLINE (OPTIONAL)
--------------------------------------------------------------------------------

  Streamlit Community Cloud (free tier):
    https://streamlit.io/cloud

  Set RENTCAST_API_KEY in the app's secrets/environment — never commit .env.

  Note: hosted cache and API counters are per deployment instance, not your PC.


================================================================================
