import aiohttp
import os
import subprocess
import asyncio
import tempfile
import shutil
from pydub import AudioSegment
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp


@register("明航音乐", "青云制作_彭明航", "一款由彭明航独立开发的AstrBot插件，专门用于获取全网免费音乐。", "1.0.0", "https://github.com/pmh1314520/astrbot_plugin_qymusic")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.session = aiohttp.ClientSession()

    async def terminate(self):
        if self.session:
            await self.session.close()

    @filter.command_group("音乐")
    def 音乐(self):
        pass

    @音乐.command("搜索")
    async def 搜索音乐(self, event: AstrMessageEvent, MusicName: str):
        '''音乐 搜索 音乐名：该指令用于搜索音乐列表。'''
        api_url = "https://music.pmhs.top/search"
        params = {'name': MusicName}

        try:
            async with self.session.get(api_url, params=params) as response:
                response.raise_for_status()
                search_results = await response.json()
        except aiohttp.ClientError as e:
            yield event.plain_result(f"抱歉，请求音乐API时出错了: {e}")
            return
        except Exception as e:
            yield event.plain_result(f"发生了一个未知错误: {e}")
            return

        if not search_results:
            yield event.plain_result(f"没有找到关于 '{MusicName}' 的歌曲。")
            return

        reply_message = f"🎵 为您找到 {len(search_results)} 首相关歌曲：\n\n"
        for index, song in enumerate(search_results, 1):
            artists_str = ", ".join(song['artist'])
            reply_message += (
                f"{index}、{song.get('album', '未知歌曲名')}\n"
                f"🎤 歌手: {artists_str}\n"
                f"📟 音乐ID: `{song['id']}`\n\n"
            )
        
        reply_message += "💡 请使用 `音乐 播放 <音乐ID>` 来点播歌曲。"
        
        yield event.plain_result(reply_message)

    @音乐.command("播放")
    async def 播放音乐(self, event: AstrMessageEvent, MusicId: str):
        '''音乐 播放 音乐ID：该指令用于获取音乐，并以语音形式发给用户。'''
        api_url = "https://music.pmhs.top/song"
        params = {'id': MusicId}

        # 创建一个临时目录用于存放下载和转换的文件
        temp_dir = tempfile.mkdtemp()
        conversion_successful = False  # 标记转换是否成功

        try:
            # 1. 获取音乐URL
            async with self.session.get(api_url, params=params) as response:
                response.raise_for_status()
                song_data = await response.json()

            if not song_data or 'url' not in song_data:
                yield event.plain_result(f"抱歉，无法找到ID为 `{MusicId}` 的歌曲播放链接。")
                return

            song_url = song_data['url']

            # 定义文件路径
            downloaded_file_path = os.path.join(temp_dir, f"{MusicId}.mp3")
            wav_file_path = os.path.join(temp_dir, f"{MusicId}.wav")

            # 2. 下载音乐文件
            yield event.plain_result("🎶 正在获取音乐，请稍候...")
            async with self.session.get(song_url, timeout=aiohttp.ClientTimeout(total=120)) as r:
                r.raise_for_status()
                with open(downloaded_file_path, 'wb') as f:
                    async for chunk in r.content.iter_chunked(8192):
                        f.write(chunk)

            # 3. 转换为WAV格式
            yield event.plain_result("🔄 正在转换音频格式...")
            await asyncio.to_thread(self._convert_to_wav, downloaded_file_path, wav_file_path)

            # 4. 发送WAV文件
            chain = [
                Comp.At(qq=event.get_sender_id()),
                Comp.Record(file=wav_file_path, url=wav_file_path),
                Comp.Plain("🎵 音乐发送完毕~")
            ]
            yield event.chain_result(chain)

            # --- 关键修改点 ---
            # 只有在成功发送语音后，才认为整个过程成功
            conversion_successful = True

        except aiohttp.ClientError as e:
            yield event.plain_result(f"❌ 下载音乐失败: {e}")
        except Exception as e:
            # 捕获转换或发送过程中可能发生的异常
            yield event.plain_result(f"❌ 处理音乐时发生错误: {e}")
            # 关键：在失败时，打印出临时目录的路径
            yield event.plain_result(f"🔍 调试信息：失败的文件已保存在临时目录，请查看：\n`{temp_dir}`")
        finally:
            # 5. 清理临时文件
            if conversion_successful:
                try:
                    shutil.rmtree(temp_dir)
                    print(f"成功，临时目录 {temp_dir} 已清理。")
                except OSError as e:
                    print(f"清理临时目录时出错: {e}")
            else:
                print(f"转换失败，临时目录 {temp_dir} 已保留，请手动检查。")


    def _convert_to_wav(self, input_path: str, output_path: str):
        """一个同步的辅助函数，跨平台调用 ffmpeg 进行转换。"""
        import subprocess
        import os

        try:
            # --- 根据平台决定如何调用 ffmpeg ---
            if os.name == 'nt':  # Windows 系统
                # 在插件目录下查找 ffmpeg.exe
                plugin_dir = os.path.dirname(os.path.abspath(__file__))
                ffmpeg_name = "ffmpeg.exe"
                FFMPEG_PATH = os.path.join(plugin_dir, ffmpeg_name)

                if not os.path.exists(FFMPEG_PATH):
                    raise RuntimeError(
                        f"音频转换失败: 在插件目录未找到 {ffmpeg_name}。\n"
                        f"请确保您已将 {ffmpeg_name} 复制到插件目录下。\n"
                        f"查找路径: {FFMPEG_PATH}"
                    )
                command = [FFMPEG_PATH]
                creation_flags = subprocess.CREATE_NO_WINDOW

            else:  # Linux/macOS 系统
                # 直接调用系统 PATH 中的 ffmpeg 命令
                command = ["ffmpeg"]
                creation_flags = 0

            # --- 构建完整的 ffmpeg 命令 ---
            command.extend([
                "-y", 
                "-i", input_path, 
                output_path
            ])

            print(f"--- 跨平台调用 FFmpeg ---")
            print(f"执行命令: {' '.join(command)}")
            print(f"-------------------------")

            # --- 执行命令 ---
            result = subprocess.run(
                command, 
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                creationflags=creation_flags
            )
            
            print("转换成功！")

        except RuntimeError as e:
            # 重新抛出我们自定义的错误（如文件未找到）
            raise e
        except FileNotFoundError:
            # 这个错误在 Linux 上可能意味着 ffmpeg 未安装
            raise RuntimeError(
                "音频转换失败: 未找到 'ffmpeg' 命令。\n"
                "在 Linux/macOS 上，请确保您已通过 'sudo apt install ffmpeg' 或类似命令安装了 ffmpeg。"
            )
        except subprocess.CalledProcessError as e:
            # 捕获 ffmpeg 执行失败
            error_detail = f"FFmpeg 执行失败。\n退出码: {e.returncode}\n标准错误:\n{e.stderr}"
            raise RuntimeError(f"音频转换失败: {error_detail}")
        except Exception as e:
            # 捕获其他未知错误
            raise RuntimeError(f"音频转换时发生未知错误: {e}")


