import streamlit as st
import requests
import os
import zipfile
import tempfile
import subprocess
import shutil
import datetime

CLIENT_ID = st.secrets["github"]["client_id"]
CLIENT_SECRET = st.secrets["github"]["client_secret"]
REDIRECT_URI = "https://pushbot.streamlit.app"

st.set_page_config(page_title="GitHub Repo Pusher", layout="centered")
st.title("🚀 GitHub Repo Pusher (New Repo Only)")

if "access_token" not in st.session_state:
    login_url = f"https://github.com/login/oauth/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=repo"
    st.markdown(f"[Login with GitHub]({login_url})")
    code = st.experimental_get_query_params().get("code")
    if code:
        code = code[0] if isinstance(code, list) else code
        res = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        ).json()
        if "access_token" in res:
            st.session_state["access_token"] = res["access_token"]
            st.success("✅ GitHub Login Successful")
            st.experimental_set_query_params()
        else:
            st.error(f"GitHub Auth Failed: {res}")

if "access_token" in st.session_state:
    headers = {"Authorization": f"token {st.session_state['access_token']}"}
    user = requests.get("https://api.github.com/user", headers=headers).json()
    if "login" not in user:
        st.error(f"GitHub login failed: {user}")
        st.stop()
    st.success(f"👋 Logged in as *{user['login']}*")

    repo_name = st.text_input("Repository name")
    description = st.text_area("Repository description (optional)")
    private = st.checkbox("Private repository?", value=False)
    commit_message = st.text_input("Commit message", value="Commit from Streamlit App")
    branch_name = st.text_input("Branch name", value="main")
    add_readme = st.checkbox("Include README.md?", value=True)
    readme_content = st.text_area("README.md content", value=f"# {repo_name}\n\n{description}") if add_readme else ""
    add_gitignore = st.checkbox("Include .gitignore?", value=True)
    gitignore_patterns = st.text_area("Enter .gitignore patterns (one per line)", value=".log\n.tmp") if add_gitignore else ""

    license_list = requests.get("https://api.github.com/licenses", headers=headers).json()
    license_options = ["None"] + [l["key"] for l in license_list if "key" in l]
    license_choice = st.selectbox("Choose a LICENSE", license_options, index=0)

    uploaded_files = st.file_uploader("Upload files", accept_multiple_files=True)
    uploaded_zip = st.file_uploader("Or upload a ZIP file", type=["zip"])

    if st.button("🚀 Create & Push Repository"):
        if not repo_name:
            st.error("Please enter a repository name.")
        else:
            repo_data = {"name": repo_name, "description": description, "private": private}
            response = requests.post("https://api.github.com/user/repos", headers=headers, json=repo_data)
            if response.status_code != 201:
                st.error(f"Failed to create repo: {response.json()}")
                st.stop()
            repo_url = response.json()["clone_url"]

            temp_dir = tempfile.mkdtemp()
            try:
                os.chdir(temp_dir)
                subprocess.run(["git", "init"], check=True)
                subprocess.run(["git", "config", "user.email", f"{user['login']}@users.noreply.github.com"])
                subprocess.run(["git", "config", "user.name", user["login"]])
                subprocess.run(["git", "lfs", "install"], check=True)

                if add_readme:
                    with open("README.md", "w", encoding="utf-8") as f:
                        f.write(readme_content)
                if add_gitignore:
                    with open(".gitignore", "w", encoding="utf-8") as f:
                        f.write(gitignore_patterns)

                if license_choice != "None":
                    lic_res = requests.get(
                        f"https://api.github.com/licenses/{license_choice}",
                        headers={"Accept": "application/vnd.github.v3.raw"}
                    )
                    if lic_res.status_code == 200:
                        license_text = lic_res.text
                        year = datetime.datetime.now().year
                        if "[year]" in license_text or "[fullname]" in license_text:
                            license_text = license_text.replace("[year]", str(year))
                            license_text = license_text.replace("[fullname]", user["login"])
                        else:
                            license_text = f"Copyright (c) {year} {user['login']}\n\n{license_text}"
                        with open("LICENSE", "w", encoding="utf-8") as f:
                            f.write(license_text)

                lfs_files = []
                for file in uploaded_files:
                    with open(file.name, "wb") as f:
                        f.write(file.read())
                    if os.path.getsize(file.name) > 100 * 1024 * 1024:
                        lfs_files.append(file.name)

                if uploaded_zip:
                    with zipfile.ZipFile(uploaded_zip, "r") as zip_ref:
                        zip_ref.extractall(temp_dir)
                    for root, _, files in os.walk(temp_dir):
                        for f_name in files:
                            path = os.path.join(root, f_name)
                            if os.path.getsize(path) > 100 * 1024 * 1024:
                                rel_path = os.path.relpath(path, temp_dir)
                                lfs_files.append(rel_path)

                for f_name in lfs_files:
                    subprocess.run(["git", "lfs", "track", f_name], check=True)
                if lfs_files:
                    with open(".gitattributes", "w") as f:
                        for f_name in lfs_files:
                            f.write(f"{f_name} filter=lfs diff=lfs merge=lfs -text\n")

                subprocess.run(["git", "add", "."])
                subprocess.run(["git", "commit", "-m", commit_message])
                remote_url = repo_url.replace("https://", f"https://{user['login']}:{st.session_state['access_token']}@")
                subprocess.run(["git", "remote", "add", "origin", remote_url])
                subprocess.run(["git", "branch", "-M", branch_name])
                subprocess.run(["git", "push", "-u", "origin", branch_name], check=True)

                st.success(f"🎉 Repository '{repo_name}' created and files pushed successfully!")
                if lfs_files:
                    st.info(f"ℹ️ {len(lfs_files)} large file(s) tracked using Git LFS")
                st.write(f"🌍 View repo: [GitHub Link]({repo_url})")
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
