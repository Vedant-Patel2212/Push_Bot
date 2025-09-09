import streamlit as st
import requests
import os
import zipfile
import tempfile
import subprocess
import shutil

CLIENT_ID = st.secrets["github"]["client_id"]
CLIENT_SECRET = st.secrets["github"]["client_secret"]
REDIRECT_URI = "https://pushbot.streamlit.app"

st.set_page_config(page_title="GitHub Repo Pusher", layout="centered")
st.title("GitHub Repo Pusher with Git LFS Support")

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
            st.success("GitHub Login Successful")
            st.query_params.clear()
        else:
            st.error(f"GitHub Auth Failed: {res}")

if "access_token" in st.session_state:
    headers = {"Authorization": f"token {st.session_state['access_token']}"}
    user = requests.get("https://api.github.com/user", headers=headers).json()
    if "login" in user:
        st.success(f"Logged in as *{user['login']}*")
    else:
        st.error(f"GitHub login failed: {user}")
        st.stop()

    mode = st.radio("Select Mode", ["Create New Repo", "Upload to Existing Repo"])
    repo_name = st.text_input("Repository name")
    description = st.text_area("Repository description (optional)") if mode == "Create New Repo" else None
    private = st.checkbox("Private repository?", value=False) if mode == "Create New Repo" else None
    commit_message = st.text_input("Commit message", value="Commit from Streamlit App")
    branch_name = st.text_input("Branch name", value="main")
    readme_content = st.text_area("README.md content", value=f"# {repo_name}\n\n{description}") if mode == "Create New Repo" else None

    uploaded_files = st.file_uploader("Upload files", accept_multiple_files=True)
    uploaded_zip = st.file_uploader("Or upload a ZIP file", type=["zip"])
    gitignore_patterns = st.text_area("Enter .gitignore patterns (one per line)", value=".log\n.tmp")

    target_folder = "/"
    if mode == "Upload to Existing Repo" and repo_name:
        repo_check = requests.get(f"https://api.github.com/repos/{user['login']}/{repo_name}/contents", headers=headers)
        if repo_check.status_code == 200:
            contents = repo_check.json()
            folders = [item["path"] for item in contents if item["type"] == "dir"]
            target_folder = st.selectbox("Select folder to push file into", ["/ (root)"] + folders)

    if st.button("Push Files"):
        if not repo_name:
            st.error("Please enter a repository name.")
        else:
            if mode == "Create New Repo":
                repo_data = {"name": repo_name, "description": description, "private": private}
                response = requests.post("https://api.github.com/user/repos", headers=headers, json=repo_data)
                if response.status_code != 201:
                    st.error(f"Failed to create repo: {response.json()}")
                    st.stop()
                st.success(f"Repository '{repo_name}' created successfully.")
                repo_url = response.json()["clone_url"]
            else:
                repo_check = requests.get(f"https://api.github.com/repos/{user['login']}/{repo_name}", headers=headers)
                if repo_check.status_code != 200:
                    st.error(f"Repository '{repo_name}' not found.")
                    st.stop()
                st.success(f"Found existing repository '{repo_name}'.")
                repo_url = repo_check.json()["clone_url"]

            temp_dir = tempfile.mkdtemp()
            try:
                if mode == "Upload to Existing Repo":
                    auth_repo_url = repo_url.replace("https://", f"https://{user['login']}:{st.session_state['access_token']}@")
                    subprocess.run(["git", "clone", auth_repo_url, temp_dir], check=True)
                else:
                    subprocess.run(["git", "init"], check=True, cwd=temp_dir)
                    with open(os.path.join(temp_dir, "README.md"), "w", encoding="utf-8") as f:
                        f.write(readme_content)

                subprocess.run(["git", "lfs", "install"], check=True, cwd=temp_dir)
                subprocess.run(["git", "config", "user.name", user["login"]], check=True, cwd=temp_dir)
                subprocess.run(["git", "config", "user.email", f"{user['login']}@users.noreply.github.com"], check=True, cwd=temp_dir)

                large_files = []
                save_path = temp_dir if target_folder == "/ (root)" else os.path.join(temp_dir, target_folder)
                os.makedirs(save_path, exist_ok=True)

                if uploaded_files:
                    for file in uploaded_files:
                        file_path = os.path.join(save_path, file.name)
                        with open(file_path, "wb") as f:
                            f.write(file.read())
                        if os.path.getsize(file_path) > 100 * 1024 * 1024:
                            rel_path = os.path.relpath(file_path, temp_dir)
                            large_files.append(rel_path)

                if uploaded_zip:
                    with zipfile.ZipFile(uploaded_zip, "r") as zip_ref:
                        zip_ref.extractall(save_path)
                    for root, _, files in os.walk(save_path):
                        for f_name in files:
                            path = os.path.join(root, f_name)
                            if os.path.getsize(path) > 100 * 1024 * 1024:
                                rel_path = os.path.relpath(path, temp_dir)
                                large_files.append(rel_path)

                if large_files:
                    for f in large_files:
                        subprocess.run(["git", "lfs", "track", f], check=True, cwd=temp_dir)
                    with open(os.path.join(temp_dir, ".gitattributes"), "a") as f:
                        for f in large_files:
                            f.write(f"{f} filter=lfs diff=lfs merge=lfs -text\n")
                    subprocess.run(["git", "add", ".gitattributes"], check=True, cwd=temp_dir)

                with open(os.path.join(temp_dir, ".gitignore"), "w") as f:
                    f.write(gitignore_patterns)

                subprocess.run(["git", "add", "."], check=True, cwd=temp_dir)
                subprocess.run(["git", "commit", "-m", commit_message], check=True, cwd=temp_dir)

                remote_url = repo_url.replace("https://", f"https://{user['login']}:{st.session_state['access_token']}@")
                subprocess.run(["git", "remote", "add", "origin", remote_url], check=False, cwd=temp_dir)
                subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True, cwd=temp_dir)

                if branch_name == "master":
                    result = subprocess.run(["git", "ls-remote", "--heads", "origin", "master"], cwd=temp_dir, capture_output=True, text=True)
                    if not result.stdout.strip():
                        branch_name = "main"

                subprocess.run(["git", "checkout", "-B", branch_name], check=True, cwd=temp_dir)
                subprocess.run(["git", "push", "-u", "origin", branch_name], check=True, cwd=temp_dir)

                st.success(f"Files pushed successfully to branch '{branch_name}'!")
                if large_files:
                    st.info(f"{len(large_files)} large file(s) tracked using Git LFS")
                st.write(f"View repo: [GitHub Link]({repo_url})")
            finally:
                shutil.rmtree(temp_dir)
