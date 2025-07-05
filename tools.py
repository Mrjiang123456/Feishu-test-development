from langchain_core.tools import tool
from langchain.tools import BaseTool
from typing import Optional
import os
import traceback
import subprocess


class Create_File(BaseTool):
    name: str = "create_file"
    description: str = "Create a new file with the provided contents at a given path in the workspace."

    def _run(self, file_name: str, file_contents: str) -> str:
        """
        Create a new file with the provided contents at a given path in the workspace.
        
        args:
            file_name (str): Name to the file to be created
            file_contents (str): The content to write to the file
        """
        try:

            file_path = os.path.join(os.getcwd(), file_name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, 'w') as file:
                file.write(file_contents)

            return {
                "message": f"Successfully created file at {file_path}"
            }

        except Exception as e:
            return {
                "error": str(e)
            }

class Str_Replace(BaseTool):
    name: str = "str_replace"
    description: str = "Replace specific text in a file."

    def _run(self, file_name: str, old_str: str, new_str: str):
        """
        Replace specific text in a file.
        
        args:
            file_name (str): Name to the target file
            old_str (str): Text to be replaced (must appear exactly once)
            new_str (str): Replacement text
        """
        try:
            file_path = os.path.join(os.getcwd(), file_name)
            with open(file_path, "r") as file:
                content = file.read()

            new_content = content.replace(old_str, new_str, 1)
            
            with open(file_path, "w") as file:
                file.write(new_content)

            return {"message": f"Successfully replaced '{old_str}' with '{new_str}' in {file_path}"}
        except Exception as e:
            return {"error": f"Error replacing '{old_str}' with '{new_str}' in {file_path}: {str(e)}"}


class Send_Message(BaseTool):
    name: str = "send_message"
    description: str = "send a message to the user"

    def _run(self, message: str):
        """
        send a message to the user
        
        args:
            message: the message to send to the user
        """
        return message


class Shell_Exec(BaseTool):
    name: str = "shell_exec"
    description: str = "在指定的 shell 会话中执行命令。"

    def _run(self, command: str) -> dict:
        """
        在指定的 shell 会话中执行命令。

        参数:
            command (str): 要执行的 shell 命令

        返回:
            dict: 包含以下字段：
                - stdout: 命令的标准输出
                - stderr: 命令的标准错误
        """
    
        try:
            # 执行命令
            result = subprocess.run(
                command,
                shell=True,          
                cwd=os.getcwd(),        
                capture_output=True,
                text=True,    
                check=False
            )

            # 返回结果
            return {"message":{"stdout": result.stdout,"stderr": result.stderr}}

        except Exception as e:
            return {"error":{"stderr": str(e)}}


# 初始化agents工具
create_file = Create_File()
str_replace = Str_Replace()
send_message = Send_Message()
shell_exec = Shell_Exec()
tools = {
    "create_file": create_file,
    "str_replace": str_replace,
    "shell_exec": shell_exec
} 