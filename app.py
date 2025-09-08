import os
import tempfile
import subprocess
import streamlit as st

st.title("GitHub File Uploader with LFS")

repo_url = st.text_input("Repository URL (HTTPS)", "")
branch_name = st.text_input("Branch name", "main")
uploaded_files = st.file_uploader("Upload files", accept_multiple_files=True)

if st.button("Upload to GitHub"):
    if not repo_url or not uploaded_files:
        st.error("Please provide repository URL and upload at least one file.")
    else:
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                subprocess.run(["git", "clone", repo_url, temp_dir], check=True)
            except subprocess.CalledProcessError:
                subprocess.run(["git", "init"], check=True, cwd=temp_dir)
                subprocess.run(["git", "remote", "add", "origin", repo_url], check=True, cwd=temp_dir)

            repo_path = temp_dir

            large_files = []
            for uploaded_file in uploaded_files:
                file_path = os.path.join(repo_path, uploaded_file.name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                if os.path.getsize(file_path) > 100 * 1024 * 1024:
                    large_files.append(uploaded_file.name)

            if large_files:
                subprocess.run(["git", "lfs", "install"], check=True, cwd=repo_path)
                for file_name in large_files:
                    subprocess.run(["git", "lfs", "track", file_name], check=True, cwd=repo_path)
                with open(os.path.join(repo_path, ".gitattributes"), "w") as attr_file:
                    for file_path in large_files:
                        attr_file.write(f"{file_path} filter=lfs diff=lfs merge=lfs -text\n")
                subprocess.run(["git", "add", ".gitattributes"], check=True, cwd=repo_path)

            subprocess.run(["git", "checkout", "-B", branch_name], check=True, cwd=repo_path)
            subprocess.run(["git", "add", "."], check=True, cwd=repo_path)

            try:
                subprocess.run(["git", "commit", "-m", "by system"], check=True, cwd=repo_path)
            except subprocess.CalledProcessError:
                st.warning("No changes to commit.")

            result = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", branch_name],
                cwd=repo_path,
                capture_output=True,
                text=True
            )

            if result.stdout.strip() == "":
                st.info(f"Branch '{branch_name}' does not exist. Creating it.")
                subprocess.run(["git", "push", "origin", f"HEAD:{branch_name}"], check=True, cwd=repo_path)
            else:
                subprocess.run(["git", "push", "-u", "origin", branch_name], check=True, cwd=repo_path)

            st.success(f"Files uploaded to {repo_url} on branch {branch_name}")
