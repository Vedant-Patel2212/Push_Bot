import streamlit as st
import requests
import os
import zipfile
import tempfile
import subprocess
import shutil

# Load secrets
CLIENT_ID = st.secrets["github"]["client_id"]
CLIENT_SECRET = st.secrets["github"]["client_secret"]

REDIRECT_URI = "https://pushbot.streamlit.app"

st.set_page_config(page_title="GitHub Repo Pusher", layout="centered")
st.title("🚀 GitHub Repo Pusher with OAuth & Git LFS Support")

# Step 1: Login with GitHub
if "access_token" not in st.session_state:
    login_url = f"https://github.com/login/oauth/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=repo"
    st.markdown(f"[Login with GitHub]({login_url})")

    query_params = st.query_params
    code = query_params.get("code")
    if code:
        if isinstance(code, list):
            code = code[0]

        token_url = "https://github.com/login/oauth/access_token"
        headers = {"Accept": "application/json"}
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }

        res = requests.post(token_url, headers=headers, data=data).json()
        if "access_token" in res:
            st.session_state["access_token"] = res["access_token"]
            st.success("✅ GitHub Login Successful")
            st.query_params.clear()
        else:
            st.error(f"GitHub Auth Failed: {res}")

# Step 2: If logged in, fetch user
if "access_token" in st.session_state:
    headers = {"Authorization": f"token {st.session_state['access_token']}"}
    user = requests.get("https://api.github.com/user", headers=headers).json()
    if "login" in user:
        st.success(f"👋 Logged in as *{user['login']}*")
    else:
        st.error(f"GitHub login failed: {user}")
        st.stop()

    # Step 3: Enter repo details
    repo_name = st.text_input("Enter new repository name")
    description = st.text_area("Repository description (optional)")
    private = st.checkbox("Private repository?", value=False)
    commit_message = st.text_input("Commit message", value="Initial commit from Streamlit App")
    branch_name = st.text_input("Branch name", value="main")

    st.write("### Optional files")
    readme_content = st.text_area("README.md content", value=f"# {repo_name}\n\n{description}")
    license_content = st.text_area("LICENSE content", value="MIT License")  # default MIT

    st.write("### Upload your files")
    uploaded_files = st.file_uploader("Upload files", accept_multiple_files=True)
    uploaded_zip = st.file_uploader("Or upload a ZIP file", type=["zip"])

    gitignore_patterns = st.text_area("Enter .gitignore patterns (one per line)", value=".log\n.tmp")

    if st.button("🚀 Create Repo & Push"):
        if not repo_name:
            st.error("Please enter a repository name.")
        else:
            # 1. Create repository
            repo_data = {
                "name": repo_name,
                "description": description,
                "private": private,
            }
            response = requests.post("https://api.github.com/user/repos", headers=headers, json=repo_data)
            if response.status_code == 201:
                st.success(f"✅ Repository '{repo_name}' created successfully.")
                repo_url = response.json()["clone_url"]

                # 2. Create temp dir and initialize git
                temp_dir = tempfile.mkdtemp()
                try:
                    os.chdir(temp_dir)

                    # Initialize git
                    subprocess.run(["git", "init"], check=True)
                    subprocess.run(["git", "config", "user.email", f"{user['login']}@users.noreply.github.com"])
                    subprocess.run(["git", "config", "user.name", user["login"]])

                    # Initialize Git LFS
                    subprocess.run(["git", "lfs", "install"], check=True)

                    # Write README.md and LICENSE
                    with open("README.md", "w", encoding="utf-8") as f:
                        f.write(readme_content)
                    with open("LICENSE", "w", encoding="utf-8") as f:
                        f.write(license_content)

                    # Track large files (>100MB)
                    lfs_files = []

                    # Write uploaded files
                    for file in uploaded_files:
                        with open(file.name, "wb") as f:
                            f.write(file.read())
                        if os.path.getsize(file.name) > 100 * 1024 * 1024:  # >100MB
                            lfs_files.append(file.name)

                    # Extract uploaded zip
                    if uploaded_zip is not None:
                        with zipfile.ZipFile(uploaded_zip, "r") as zip_ref:
                            zip_ref.extractall(temp_dir)
                        # Check extracted files for size >100MB
                        for root, dirs, files in os.walk(temp_dir):
                            for f_name in files:
                                path = os.path.join(root, f_name)
                                if os.path.getsize(path) > 100 * 1024 * 1024:
                                    rel_path = os.path.relpath(path, temp_dir)
                                    lfs_files.append(rel_path)

                    # Track large files in Git LFS
                    for f_name in lfs_files:
                        subprocess.run(["git", "lfs", "track", f_name], check=True)

                    # Write .gitattributes if LFS files exist
                    if lfs_files:
                        with open(".gitattributes", "w") as f:
                            for f_name in lfs_files:
                                f.write(f"{f_name} filter=lfs diff=lfs merge=lfs -text\n")

                    # Write .gitignore
                    with open(".gitignore", "w") as f:
                        f.write(gitignore_patterns)

                    # Commit and push
                    subprocess.run(["git", "add", "."])
                    subprocess.run(["git", "commit", "-m", commit_message])

                    remote_url = repo_url.replace("https://", f"https://{user['login']}:{st.session_state['access_token']}@")
                    subprocess.run(["git", "remote", "add", "origin", remote_url])

                    subprocess.run(["git", "branch", "-M", branch_name])
                    subprocess.run(["git", "push", "-u", "origin", branch_name], check=True)

                    st.success(f"🎉 Files pushed successfully to branch '{branch_name}'!")
                    if lfs_files:
                        st.info(f"ℹ️ {len(lfs_files)} large file(s) tracked using Git LFS")
                    st.write(f"🌍 View repo: [GitHub Link]({repo_url})")
                finally:
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass

            else:
                st.error(f"Failed to create repo: {response.json()}")
