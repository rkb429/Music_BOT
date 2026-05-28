import discord
from discord.ext import commands
import sqlite3
import os
import yt_dlp
import aiohttp
import html
import asyncio
import re
import math
import logging
from urllib.parse import quote

logger = logging.getLogger('discord_bot')


class PageView(discord.ui.View):
    def __init__(self, pages: list, author_id: int):
        super().__init__(timeout=60)
        self.pages = pages
        self.author_id = author_id
        self.page = 0
        self._refresh()

    def _refresh(self):
        self.prev_btn.disabled = (self.page == 0)
        self.next_btn.disabled = (self.page >= len(self.pages) - 1)

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.grey)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ 명령어 실행자만 조작할 수 있습니다.", ephemeral=True)
        self.page -= 1
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.grey)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("❌ 명령어 실행자만 조작할 수 있습니다.", ephemeral=True)
        self.page += 1
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)


class PlaylistPaginationView(discord.ui.View):
    def __init__(self, author, p_name, owner_id, songs, per_page=20, mode='show'):
        super().__init__(timeout=120)
        self.author = author
        self.p_name = p_name
        self.owner_id = owner_id
        self.songs = songs
        self.page = 0
        self.per_page = per_page
        self.mode = mode
        self.max_page = max(0, (len(songs) - 1) // per_page)
        self.update_buttons()

    def update_buttons(self):
        if hasattr(self, 'prev_btn') and hasattr(self, 'next_btn'):
            self.prev_btn.disabled = self.page == 0
            self.next_btn.disabled = self.page == self.max_page

    def generate_embed(self):
        cb = '`' * 3
        start = self.page * self.per_page
        end = start + self.per_page
        current_songs = self.songs[start:end]

        if self.mode == 'edit':
            embed = discord.Embed(title=f"📝 '{self.p_name}' 수정", color=0xe67e22)
        else:
            embed = discord.Embed(title=f"📄 '{self.p_name}' 수록곡 (제작: <@{self.owner_id}>)", color=0x3498db)

        song_list_text = ""
        for i, row in enumerate(current_songs):
            title = row[-1]
            song_list_text += f"{start + i + 1}. {title}\n"

        if not song_list_text:
            song_list_text = "곡이 없습니다."

        embed.description = f"{cb}\n{song_list_text}\n{cb}"
        embed.set_footer(text=f"페이지 {self.page + 1} / {self.max_page + 1} | 총 {len(self.songs)}곡")
        return embed

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.primary, custom_id="prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("❌ 본인만 조작 가능합니다.", ephemeral=True)
        if self.page > 0:
            self.page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.generate_embed(), view=self)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.primary, custom_id="next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("❌ 본인만 조작 가능합니다.", ephemeral=True)
        if self.page < self.max_page:
            self.page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.generate_embed(), view=self)
        else:
            await interaction.response.defer()


class PlaylistSelect(discord.ui.Select):
    def __init__(self, cog, author, mode, options_data):
        self.cog = cog
        self.author = author
        self.mode = mode

        opts = []
        if mode == 'show_contents':
            for p_name, owner_id, count in options_data[:25]:
                opts.append(discord.SelectOption(
                    label=p_name,
                    description=f"제작: {owner_id} ({count}곡)",
                    value=f"{owner_id}:{p_name}",
                    emoji="📄"
                ))
            ph = "수록곡을 확인할 플리 선택..."

        elif mode == 'play':
            for p_name, owner_id, count in options_data[:25]:
                opts.append(discord.SelectOption(
                    label=p_name,
                    description=f"제작: {owner_id} ({count}곡 대기열 추가)",
                    value=f"{owner_id}:{p_name}",
                    emoji="▶️"
                ))
            ph = "재생할 서버 플레이리스트 선택..."

        elif mode == 'delete':
            for p_name, count in options_data[:25]:
                opts.append(discord.SelectOption(label=p_name, description=f"{count}곡 삭제", value=p_name, emoji="🗑️"))
            ph = "삭제할 본인 플리 선택..."

        elif mode == 'edit':
            for p_name, count in options_data[:25]:
                opts.append(discord.SelectOption(label=p_name, description=f"{count}곡 수정", value=p_name, emoji="✏️"))
            ph = "곡을 제거할 본인 플리 선택..."

        elif mode == 'import':
            for p_name, g_id, count in options_data[:25]:
                opts.append(discord.SelectOption(label=p_name, description=f"ID: {g_id} ({count}곡)", value=f"{g_id}:{p_name}"))
            ph = "가져올 외부 서버 플리 선택..."

        elif mode == 'export':
            guilds, p_name, songs = options_data
            self.p_name = p_name
            self.songs = songs
            for g in guilds[:25]:
                opts.append(discord.SelectOption(label=g.name, description=f"ID: {g.id}", value=str(g.id)))
            ph = "내보낼 대상 서버 선택..."

        super().__init__(placeholder=ph, options=opts)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("❌ 본인만 조작 가능합니다.", ephemeral=True)

        await interaction.response.defer()
        uid = str(self.author.id)
        gid = str(interaction.guild.id)

        if self.mode == 'show_contents':
            parts = self.values[0].split(':', 1)
            if len(parts) < 2:
                return
            owner_id, p_name = parts
            table = f"{owner_id}_{p_name}"

            with self.cog.get_local_conn(gid) as conn:
                try:
                    songs = conn.execute(f'SELECT title FROM "{table}"').fetchall()
                except sqlite3.OperationalError:
                    return await interaction.edit_original_response(content=f"❌ '{p_name}' 테이블이 DB에 존재하지 않습니다.", view=None)

            if not songs:
                return await interaction.edit_original_response(content=f"📭 `{p_name}` 플리가 비어있습니다.", view=None)

            pagination_view = PlaylistPaginationView(self.author, p_name, owner_id, songs, mode='show')
            embed = pagination_view.generate_embed()
            await interaction.edit_original_response(content=None, embed=embed, view=pagination_view)

        elif self.mode == 'play':
            parts = self.values[0].split(':', 1)
            if len(parts) < 2:
                return
            owner_id, p_name = parts
            table = f"{owner_id}_{p_name}"

            with self.cog.get_local_conn(gid) as conn:
                try:
                    songs = conn.execute(f'SELECT title, url FROM "{table}"').fetchall()
                except sqlite3.OperationalError:
                    return await interaction.edit_original_response(content=f"❌ '{p_name}' 테이블이 DB에 존재하지 않습니다.", view=None)

            if not songs:
                return await interaction.edit_original_response(content=f"📭 `{p_name}` 플리가 비어있습니다. 곡을 먼저 담아주세요.", view=None)

            music_cog = self.cog.bot.get_cog('MusicCog')
            if music_cog:
                if not interaction.guild.voice_client:
                    if interaction.user.voice:
                        await interaction.user.voice.channel.connect()
                    else:
                        return await interaction.edit_original_response(content="❌ 음성 채널에 먼저 입장해주세요.", view=None)

                formatted = [{'title': s[0], 'target': s[1]} for s in songs]
                ctx = await self.cog.bot.get_context(interaction.message)
                ctx.author = interaction.user
                await music_cog.add_songs(ctx, formatted)
                await interaction.edit_original_response(content=f"▶️ `{p_name}` 플리 **{len(songs)}곡**을 대기열에 주입했습니다!", view=None)
            else:
                await interaction.edit_original_response(content="❌ 음악 엔진 로드 실패.", view=None)

        elif self.mode == 'delete':
            p_name = self.values[0]
            with self.cog.get_master_conn() as m_conn:
                verify = m_conn.execute("SELECT user_id FROM playlist_registry WHERE user_id=? AND playlist_name=?", (uid, p_name)).fetchone()
                if not verify:
                    return await interaction.edit_original_response(content="❌ 본인의 플리만 삭제할 수 있습니다.", view=None)
                m_conn.execute("DELETE FROM playlist_registry WHERE user_id=? AND playlist_name=?", (uid, p_name))
                m_conn.commit()
            with self.cog.get_local_conn(gid) as conn:
                conn.execute(f'DROP TABLE IF EXISTS "{uid}_{p_name}"')
                conn.commit()
            await interaction.edit_original_response(content=f"🗑️ `{p_name}` 삭제 완료.", view=None)

        elif self.mode == 'edit':
            p_name = self.values[0]
            table = f"{uid}_{p_name}"
            with self.cog.get_local_conn(gid) as conn:
                try:
                    songs = conn.execute(f'SELECT rowid, title FROM "{table}"').fetchall()
                except sqlite3.OperationalError:
                    return await interaction.edit_original_response(content=f"❌ '{p_name}' 테이블이 DB에 존재하지 않습니다.", view=None)

            if not songs:
                return await interaction.edit_original_response(content=f"📭 `{p_name}` 비어있습니다.", view=None)

            pagination_view = PlaylistPaginationView(self.author, p_name, uid, songs, mode='edit')
            embed = pagination_view.generate_embed()
            content_text = "채팅으로 삭제할 번호를 입력하세요 (예: `1, 3, 5` 또는 `1-10`. 취소: `취소`)"

            await interaction.edit_original_response(content=content_text, embed=embed, view=pagination_view)

            def check(m): return m.author == interaction.user and m.channel == interaction.channel
            try:
                msg = await self.cog.bot.wait_for('message', check=check, timeout=60.0)
                if msg.content == "취소":
                    return await interaction.edit_original_response(content="수정 취소됨.", embed=None, view=None)

                clean_msg = re.sub(r'\s*-\s*', '-', msg.content)
                idx_strs = clean_msg.replace(',', ' ').split()
                valid_indices = []

                for x in idx_strs:
                    if '-' in x:
                        parts = x.split('-')
                        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                            start_idx, end_idx = sorted([int(parts[0]) - 1, int(parts[1]) - 1])
                            valid_indices.extend(range(start_idx, end_idx + 1))
                    elif x.isdigit():
                        valid_indices.append(int(x) - 1)

                valid_indices = sorted(list(set([i for i in valid_indices if 0 <= i < len(songs)])), reverse=True)

                if not valid_indices:
                    return await interaction.edit_original_response(content="❌ 유효한 숫자를 찾을 수 없습니다.", embed=None, view=None)

                rowids_to_delete = [(songs[i][0],) for i in valid_indices]
                deleted_titles = [songs[i][1] for i in valid_indices]

                with self.cog.get_local_conn(gid) as conn:
                    conn.executemany(f'DELETE FROM "{table}" WHERE rowid=?', rowids_to_delete)
                    conn.commit()

                if len(deleted_titles) == 1:
                    await interaction.edit_original_response(content=f"✅ `{deleted_titles[0]}` 곡을 플리에서 삭제했습니다.", embed=None, view=None)
                else:
                    await interaction.edit_original_response(content=f"✅ `{deleted_titles[-1]}` 포함 총 **{len(deleted_titles)}곡**을 일괄 삭제했습니다.", embed=None, view=None)

            except asyncio.TimeoutError:
                await interaction.edit_original_response(content="❌ 입력 시간이 초과되어 수정이 취소되었습니다.", embed=None, view=None)

        elif self.mode == 'export':
            target_gid = self.values[0]
            table = f"{uid}_{self.p_name}"
            with self.cog.get_local_conn(target_gid) as conn:
                conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (title TEXT, url TEXT)')
                conn.execute(f'DELETE FROM "{table}"')
                for t, u in self.songs:
                    conn.execute(f'INSERT INTO "{table}" VALUES (?, ?)', (t, u))
                conn.commit()

            with self.cog.get_master_conn() as m_conn:
                m_conn.execute("INSERT OR REPLACE INTO playlist_registry VALUES (?, ?, ?)", (uid, self.p_name, target_gid))
                m_conn.commit()
            await interaction.edit_original_response(content=f"✅ `{self.p_name}` 전송 완료!", view=None)

        elif self.mode == 'import':
            src_gid, p_name = self.values[0].split(':', 1)
            with self.cog.get_local_conn(src_gid) as conn_src:
                songs_data = conn_src.execute(f'SELECT * FROM "{uid}_{p_name}"').fetchall()

            table = f"{uid}_{p_name}"
            with self.cog.get_local_conn(gid) as conn_dest:
                conn_dest.execute(f'CREATE TABLE IF NOT EXISTS "{table}" (title TEXT, url TEXT)')
                conn_dest.execute(f'DELETE FROM "{table}"')
                for t, u in songs_data:
                    conn_dest.execute(f'INSERT INTO "{table}" VALUES (?, ?)', (t, u))
                conn_dest.commit()
            await interaction.edit_original_response(content=f"✅ `{p_name}` 불러오기 성공!", view=None)


class PlaylistView(discord.ui.View):
    def __init__(self, cog, author, mode, data):
        super().__init__(timeout=60)
        self.add_item(PlaylistSelect(cog, author, mode, data))


class DatabaseCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        try:
            with self.get_master_conn() as m_conn:
                m_conn.execute('''
                    CREATE TABLE IF NOT EXISTS playlist_registry (
                        user_id TEXT NOT NULL,
                        playlist_name TEXT NOT NULL,
                        guild_id TEXT NOT NULL,
                        PRIMARY KEY (user_id, playlist_name)
                    )
                ''')
                m_conn.execute('''
                    CREATE TABLE IF NOT EXISTS play_history (
                        user_id TEXT NOT NULL,
                        guild_id TEXT NOT NULL,
                        song_title TEXT NOT NULL,
                        song_url TEXT NOT NULL,
                        artist TEXT,
                        play_count INTEGER DEFAULT 1,
                        last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, guild_id, song_url)
                    )
                ''')
                m_conn.execute('CREATE INDEX IF NOT EXISTS idx_play_history_user_guild ON play_history(user_id, guild_id)')
                m_conn.execute('CREATE INDEX IF NOT EXISTS idx_play_history_play_count ON play_history(play_count DESC)')
                m_conn.commit()
        except Exception as e:
            logger.error(f"[DatabaseCog] 마스터 DB 초기화 오류: {e}")

        self.ytdl = yt_dlp.YoutubeDL({
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'playlistend': 100,
        })
        self.ytdl_search = yt_dlp.YoutubeDL({
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'default_search': 'ytsearch',
            'nocheckcertificate': True,
        })

        self.api_key = None
        try:
            with open(os.path.join(self.base, 'youtube_key.txt'), 'r', encoding='utf-8') as f:
                self.api_key = f.read().strip()
        except (FileNotFoundError, OSError):
            logger.warning("[DatabaseCog] youtube_key.txt를 찾을 수 없습니다. YouTube API 검색 기능이 비활성화됩니다.")

    def sanitize_name(self, name: str) -> str:
        return name.strip().replace('"', '').replace("'", "").replace(';', '').replace('`', '').replace('%', '')

    def get_master_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(os.path.join(self.base, 'master_index.db'))

    def get_local_conn(self, gid: str) -> sqlite3.Connection:
        return sqlite3.connect(os.path.join(self.base, f'guild_{gid}.db'))

    async def search_yt(self, q: str):
        if not self.api_key:
            return None
        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&maxResults=1&q={quote(q)}&type=video&key={self.api_key}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status == 200:
                    d = await r.json()
                    if d.get('items'):
                        return {'url': f"https://www.youtube.com/watch?v={d['items'][0]['id']['videoId']}",
                                'title': html.unescape(d['items'][0]['snippet']['title'])}
                else:
                    logger.error(f"[YouTube API] 상태 코드 오류: {r.status}")
        return None

    @commands.command(name='플리생성')
    async def create_p(self, ctx, *, name: str):
        name = self.sanitize_name(name)
        if not name:
            return await ctx.send("❌ 사용할 수 없는 이름입니다.")

        gid, uid = str(ctx.guild.id), str(ctx.author.id)
        try:
            with self.get_master_conn() as m_conn:
                m_conn.execute("INSERT INTO playlist_registry VALUES (?, ?, ?)", (uid, name, gid))
                m_conn.commit()
            with self.get_local_conn(gid) as conn:
                conn.execute(f'CREATE TABLE IF NOT EXISTS "{uid}_{name}" (title TEXT, url TEXT)')
                conn.commit()
            await ctx.send(f"✅ 플리 `{name}` 생성 완료!")
        except sqlite3.IntegrityError:
            await ctx.send("❌ 이미 존재하는 플리 이름입니다.")
        except sqlite3.Error as e:
            logger.error(f"[DatabaseCog] 플리 생성 DB 오류: {e}")
            await ctx.send("❌ DB 오류가 발생했습니다.")

    @commands.command(name='담기')
    async def add_p(self, ctx, p_name: str, *, search: str):
        p_name = self.sanitize_name(p_name)
        uid, gid = str(ctx.author.id), str(ctx.guild.id)
        table = f"{uid}_{p_name}"

        try:
            with self.get_local_conn(gid) as conn:
                if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    return await ctx.send("❌ 본인 소유의 플리를 찾을 수 없습니다.")
        except sqlite3.Error as e:
            logger.error(f"[DatabaseCog] 담기 DB 조회 오류: {e}")
            return await ctx.send("❌ DB 오류가 발생했습니다.")

        msg = await ctx.send("🔍 곡 정보를 가져오는 중입니다...")
        songs = []
        try:
            if not search.startswith('http'):
                res = await self.search_yt(search)
                if not res:
                    try:
                        data = await self.bot.loop.run_in_executor(
                            None, lambda: self.ytdl_search.extract_info(f"ytsearch1:{search}", download=False)
                        )
                        if data and data.get('entries') and data['entries'][0]:
                            e = data['entries'][0]
                            vid_id = e.get('id', '')
                            res = {
                                'url': e.get('url') or (f"https://www.youtube.com/watch?v={vid_id}" if vid_id else None),
                                'title': e.get('title', search),
                            }
                    except Exception as yt_err:
                        logger.error(f"[DatabaseCog] yt_dlp 검색 fallback 오류: {yt_err}")
                if res and res.get('url'):
                    songs.append(res)
            else:
                try:
                    data = await self.bot.loop.run_in_executor(None, lambda: self.ytdl.extract_info(search, download=False))
                    if not data:
                        return await msg.edit(content="❌ 곡 정보를 찾을 수 없습니다.")
                    if 'entries' in data:
                        for e in data['entries']:
                            if e:
                                vid = e.get('id')
                                video_url = e.get('webpage_url') or e.get('original_url') or (f"https://www.youtube.com/watch?v={vid}" if vid else e.get('url'))
                                title = e.get('title')
                                if video_url and title:
                                    songs.append({'url': video_url, 'title': title})
                    else:
                        vid = data.get('id')
                        video_url = data.get('webpage_url') or data.get('original_url') or (f"https://www.youtube.com/watch?v={vid}" if vid else data.get('url'))
                        title = data.get('title')
                        if video_url and title:
                            songs.append({'url': video_url, 'title': title})
                except Exception as yt_err:
                    logger.error(f"[DatabaseCog] ytdl 추출 오류: {yt_err}")
                    return await msg.edit(content="❌ 오류가 발생했습니다: 유효하지 않은 링크이거나 추출에 실패했습니다.")

            if not songs:
                return await msg.edit(content="❌ 곡 정보를 찾을 수 없습니다. (비공개 또는 삭제된 영상일 수 있습니다.)")

            with self.get_local_conn(gid) as conn:
                for s in songs:
                    conn.execute(f'INSERT INTO "{table}" VALUES (?, ?)', (s['title'], s['url']))
                conn.commit()
            await msg.edit(content=f"✅ **{len(songs)}곡**을 `{p_name}`에 저장했습니다!")
        except sqlite3.Error as db_err:
            logger.error(f"[DatabaseCog] 곡 저장 DB 오류: {db_err}")
            await msg.edit(content="❌ 곡 저장 중 DB 오류가 발생했습니다.")
        except Exception as e:
            logger.error(f"담기 오류 (user={ctx.author.id}, search={search}): {e}")
            await msg.edit(content="❌ 곡 정보를 가져오는 중 시스템 오류가 발생했습니다.")

    @commands.command(name='플리내용', aliases=['플리목록'])
    async def show_p_contents(self, ctx, *, name: str = None):
        gid = str(ctx.guild.id)

        if name:
            name = self.sanitize_name(name)
            if not name:
                return await ctx.send("❌ 사용할 수 없는 이름입니다.")
            suffix = f"_{name}"
            with self.get_local_conn(gid) as conn:
                all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                table_name = next((t for (t,) in all_tables if t.endswith(suffix) and t != 'sqlite_sequence' and '_' in t), None)
                if not table_name:
                    return await ctx.send("❌ 해당 플리를 찾을 수 없습니다.")
                owner_id = table_name.split('_', 1)[0]
                songs = conn.execute(f'SELECT title FROM "{table_name}"').fetchall()

            if not songs:
                return await ctx.send(f"📭 `{name}` 비어있습니다.")

            pagination_view = PlaylistPaginationView(ctx.author, name, owner_id, songs, mode='show')
            embed = pagination_view.generate_embed()
            await ctx.send(embed=embed, view=pagination_view)
        else:
            opts = []
            with self.get_local_conn(gid) as conn:
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                for (t,) in tables:
                    if t == 'sqlite_sequence':
                        continue
                    try:
                        t_owner, p_name = t.split('_', 1)
                        count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                        opts.append((p_name, t_owner, count))
                    except Exception:
                        continue

            if not opts:
                return await ctx.send("📭 서버에 등록된 플리가 없습니다.")

            await ctx.send("📄 목록을 확인할 플리 선택:", view=PlaylistView(self, ctx.author, 'show_contents', opts))

    @commands.command(name='플리수정')
    async def edit_p(self, ctx, *, name: str = None):
        uid, gid = str(ctx.author.id), str(ctx.guild.id)

        if name:
            name = self.sanitize_name(name)
            if not name:
                return await ctx.send("❌ 사용할 수 없는 이름입니다.")
            table = f"{uid}_{name}"
            try:
                with self.get_local_conn(gid) as conn:
                    if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        return await ctx.send("❌ 본인 소유의 플리만 수정할 수 있습니다.")
                    songs = conn.execute(f'SELECT rowid, title FROM "{table}"').fetchall()
            except sqlite3.OperationalError as e:
                logger.error(f"[DatabaseCog] 플리수정 DB 오류: {e}")
                return await ctx.send("❌ DB 오류가 발생했습니다.")

            if not songs:
                return await ctx.send(f"📭 `{name}` 비어있습니다.")

            pagination_view = PlaylistPaginationView(ctx.author, name, uid, songs, mode='edit')
            embed = pagination_view.generate_embed()
            content_text = "채팅으로 삭제할 번호를 입력하세요 (예: `1, 3, 5` 또는 `1-10`. 취소: `취소`)"

            prompt_msg = await ctx.send(content=content_text, embed=embed, view=pagination_view)

            def check(m): return m.author == ctx.author and m.channel == ctx.channel
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=60.0)
                if msg.content == "취소":
                    return await prompt_msg.edit(content="수정 취소됨.", embed=None, view=None)

                clean_msg = re.sub(r'\s*-\s*', '-', msg.content)
                idx_strs = clean_msg.replace(',', ' ').split()
                valid_indices = []

                for x in idx_strs:
                    if '-' in x:
                        parts = x.split('-')
                        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                            start_idx, end_idx = sorted([int(parts[0]) - 1, int(parts[1]) - 1])
                            valid_indices.extend(range(start_idx, end_idx + 1))
                    elif x.isdigit():
                        valid_indices.append(int(x) - 1)

                valid_indices = sorted(list(set([i for i in valid_indices if 0 <= i < len(songs)])), reverse=True)

                if not valid_indices:
                    return await prompt_msg.edit(content="❌ 유효한 숫자를 찾을 수 없습니다.", embed=None, view=None)

                rowids_to_delete = [(songs[i][0],) for i in valid_indices]
                deleted_titles = [songs[i][1] for i in valid_indices]

                with self.get_local_conn(gid) as conn:
                    conn.executemany(f'DELETE FROM "{table}" WHERE rowid=?', rowids_to_delete)
                    conn.commit()

                if len(deleted_titles) == 1:
                    await prompt_msg.edit(content=f"✅ `{deleted_titles[0]}` 곡을 삭제 완료.", embed=None, view=None)
                else:
                    await prompt_msg.edit(content=f"✅ `{deleted_titles[-1]}` 포함 총 **{len(deleted_titles)}곡**을 일괄 삭제 완료.", embed=None, view=None)

            except asyncio.TimeoutError:
                await prompt_msg.edit(content="❌ 입력 시간이 초과되어 수정이 취소되었습니다.", embed=None, view=None)
        else:
            opts = []
            uid_prefix = uid + "_"
            with self.get_local_conn(gid) as conn:
                all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                for (t,) in all_tables:
                    if not t.startswith(uid_prefix):
                        continue
                    parts = t.split('_', 1)
                    if len(parts) < 2:
                        continue
                    p_name = parts[1]
                    count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    opts.append((p_name, count))

            if not opts:
                return await ctx.send("❌ 이 서버에 곡을 삭제할 수 있는 본인 소유의 플레이리스트가 없습니다.")

            await ctx.send("✏️ 곡을 삭제할 플리 선택:", view=PlaylistView(self, ctx.author, 'edit', opts))

    @commands.command(name='플리재생')
    async def play_p(self, ctx, *, name: str = None):
        gid = str(ctx.guild.id)

        if name:
            name = self.sanitize_name(name)
            if not name:
                return await ctx.send("❌ 사용할 수 없는 이름입니다.")
            suffix = f"_{name}"
            with self.get_local_conn(gid) as conn:
                all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                table_match = next((t for (t,) in all_tables if t.endswith(suffix) and t != 'sqlite_sequence' and '_' in t), None)
                if not table_match:
                    return await ctx.send("❌ 서버 내에서 해당 플리를 찾지 못했습니다.")
                songs = conn.execute(f'SELECT title, url FROM "{table_match}"').fetchall()

            if not songs:
                return await ctx.send(f"📭 `{name}` 플리가 비어있습니다. 곡을 먼저 담아주세요.")

            music_cog = self.bot.get_cog('MusicCog')
            if music_cog:
                if not ctx.voice_client:
                    if ctx.author.voice:
                        await ctx.author.voice.channel.connect()
                    else:
                        return await ctx.send("❌ 음성 채널에 먼저 입장해주세요.")

                formatted = [{'title': s[0], 'target': s[1]} for s in songs]
                await music_cog.add_songs(ctx, formatted)
                await ctx.send(f"▶️ `{name}` 플리 **{len(songs)}곡**을 대기열에 주입했습니다!")
            else:
                await ctx.send("❌ 음악 엔진을 불러올 수 없습니다.")

        else:
            opts = []
            with self.get_local_conn(gid) as conn:
                tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                for (t,) in tables:
                    if t == 'sqlite_sequence':
                        continue
                    try:
                        t_owner, p_name = t.split('_', 1)
                        count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                        opts.append((p_name, t_owner, count))
                    except Exception:
                        continue

            if not opts:
                return await ctx.send("📭 이 서버에 등록된 플레이리스트가 없습니다.")

            await ctx.send("▶️ 재생할 플레이리스트를 선택하세요:", view=PlaylistView(self, ctx.author, 'play', opts))

    @commands.command(name='내플리')
    async def my_p(self, ctx):
        uid, gid = str(ctx.author.id), str(ctx.guild.id)
        uid_prefix = uid + "_"
        playlist_data = []
        with self.get_local_conn(gid) as conn:
            all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            user_tables = [t for (t,) in all_tables if t.startswith(uid_prefix)]
            if not user_tables:
                return await ctx.send("📭 이 서버에 등록된 본인의 플리가 없습니다.")
            for t in user_tables:
                parts = t.split('_', 1)
                if len(parts) < 2:
                    continue
                count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                playlist_data.append((parts[1], count))

        total = len(playlist_data)
        page_size = 10
        total_pages = max(1, math.ceil(total / page_size))
        pages = []
        for p in range(total_pages):
            chunk = playlist_data[p * page_size:(p + 1) * page_size]
            embed = discord.Embed(title=f"💿 {ctx.author.name}님의 플리", color=0x3498db)
            for p_name, count in chunk:
                embed.add_field(name=f"📁 {p_name}", value=f"{count}곡", inline=False)
            if total_pages > 1:
                embed.set_footer(text=f"{p + 1}/{total_pages} 페이지 | 총 {total}개")
            pages.append(embed)

        view = PageView(pages, ctx.author.id) if total_pages > 1 else None
        await ctx.send(embed=pages[0], view=view)

    @commands.command(name='서버플리')
    async def server_p(self, ctx):
        gid = str(ctx.guild.id)
        playlist_data = []
        with self.get_local_conn(gid) as conn:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for (t,) in tables:
                if t == 'sqlite_sequence':
                    continue
                try:
                    parts = t.split('_', 1)
                    if len(parts) < 2:
                        continue
                    uid, p_name = parts
                    count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    playlist_data.append((p_name, uid, count))
                except Exception:
                    continue

        if not playlist_data:
            return await ctx.send("📭 이 서버에 등록된 플리가 없습니다.")

        total = len(playlist_data)
        page_size = 10
        total_pages = max(1, math.ceil(total / page_size))
        pages = []
        for p in range(total_pages):
            chunk = playlist_data[p * page_size:(p + 1) * page_size]
            embed = discord.Embed(title="💿 서버 전체 플리", color=0x00ff56)
            for p_name, uid, count in chunk:
                embed.add_field(name=f"📁 {p_name}", value=f"제작: <@{uid}> ({count}곡)", inline=False)
            if total_pages > 1:
                embed.set_footer(text=f"{p + 1}/{total_pages} 페이지 | 총 {total}개")
            pages.append(embed)

        view = PageView(pages, ctx.author.id) if total_pages > 1 else None
        await ctx.send(embed=pages[0], view=view)

    @commands.command(name='플리내보내기')
    async def export_playlist(self, ctx, *, name: str):
        gid = str(ctx.guild.id)
        uid = str(ctx.author.id)
        name = self.sanitize_name(name)
        if not name:
            return await ctx.send("❌ 사용할 수 없는 이름입니다.")
        table = f"{uid}_{name}"

        with self.get_local_conn(gid) as conn:
            if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                return await ctx.send("❌ 본인 소유의 플리만 내보낼 수 있습니다.")
            songs = conn.execute(f'SELECT title, url FROM "{table}"').fetchall()

        mutual_guilds = [g for g in ctx.author.mutual_guilds if g.id != ctx.guild.id]
        if not mutual_guilds:
            return await ctx.send("❌ 보낼 서버가 없습니다.")

        view = PlaylistView(self, ctx.author, 'export', (mutual_guilds, name, songs))
        await ctx.send(f"📤 `{name}`를 보낼 서버를 선택하세요:", view=view)

    @commands.command(name='플리불러오기')
    async def import_playlist(self, ctx):
        uid = str(ctx.author.id)
        try:
            with self.get_master_conn() as m_conn:
                res = m_conn.execute("SELECT playlist_name, guild_id FROM playlist_registry WHERE user_id=?", (uid,)).fetchall()
        except sqlite3.Error as e:
            logger.error(f"[DatabaseCog] 플리불러오기 마스터 DB 조회 오류: {e}")
            return await ctx.send("❌ DB 조회 중 오류가 발생했습니다.")

        if not res:
            return await ctx.send("❌ 마스터 DB에 등록된 본인의 플리가 없습니다.")

        options_data = []
        for p_name, g_id in res:
            if g_id == str(ctx.guild.id):
                continue
            try:
                with self.get_local_conn(g_id) as conn:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{uid}_{p_name}"').fetchone()[0]
                options_data.append((p_name, g_id, count))
            except sqlite3.Error as e:
                logger.error(f"[DatabaseCog] 플리불러오기 곡 개수 조회 오류 ({p_name}): {e}")
                continue

        if not options_data:
            return await ctx.send("❌ 다른 서버에 저장된 플리가 없습니다.")

        view = PlaylistView(self, ctx.author, 'import', options_data)
        await ctx.send("🌐 불러올 플리를 선택하세요 (다른 서버의 데이터):", view=view)

    @commands.command(name='플리삭제')
    async def delete_p(self, ctx, *, name: str = None):
        uid, gid = str(ctx.author.id), str(ctx.guild.id)

        if name:
            name = self.sanitize_name(name)
            if not name:
                return await ctx.send("❌ 사용할 수 없는 이름입니다.")
            with self.get_master_conn() as m_conn:
                cursor = m_conn.execute("DELETE FROM playlist_registry WHERE user_id=? AND playlist_name=?", (uid, name))
                if cursor.rowcount == 0:
                    return await ctx.send("❌ 삭제할 플리가 없거나 본인 소유가 아닙니다.")
                m_conn.commit()

            with self.get_local_conn(gid) as conn:
                conn.execute(f'DROP TABLE IF EXISTS "{uid}_{name}"')
                conn.commit()

            return await ctx.send(f"🗑️ `{name}` 삭제 완료.")

        opts = []
        uid_prefix = uid + "_"
        with self.get_local_conn(gid) as conn:
            all_tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for (t,) in all_tables:
                if not t.startswith(uid_prefix):
                    continue
                parts = t.split('_', 1)
                if len(parts) < 2:
                    continue
                p_name = parts[1]
                count = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                opts.append((p_name, count))

        if not opts:
            return await ctx.send("❌ 이 서버에 삭제할 수 있는 본인 소유의 플레이리스트가 없습니다.")

        await ctx.send("🗑️ 삭제할 본인의 플레이리스트를 선택하세요 (⚠️복구 불가):", view=PlaylistView(self, ctx.author, 'delete', opts))

    def get_user_playlists(self, user_id: str) -> list:
        try:
            with self.get_master_conn() as m_conn:
                result = m_conn.execute(
                    "SELECT DISTINCT playlist_name FROM playlist_registry WHERE user_id=?",
                    (user_id,)
                ).fetchall()
                return [row[0] for row in result]
        except Exception as e:
            logger.error(f"[DatabaseCog] 사용자 플리 조회 오류: {e}")
            return []

    def get_playlist_songs(self, user_id: str, playlist_name: str, guild_id: str) -> list:
        try:
            with self.get_local_conn(guild_id) as conn:
                result = conn.execute(
                    f'SELECT title FROM "{user_id}_{playlist_name}"'
                ).fetchall()
                return [row[0] for row in result]
        except Exception as e:
            logger.error(f"[DatabaseCog] 플리 곡 조회 오류: {e}")
            return []

    def add_to_play_history(self, user_id: str, guild_id: str, song_title: str, song_url: str, artist: str = None) -> None:
        try:
            with self.get_master_conn() as m_conn:
                m_conn.execute('''
                    INSERT INTO play_history (user_id, guild_id, song_title, song_url, artist, play_count, last_played)
                    VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, guild_id, song_url) DO UPDATE SET
                    play_count = play_count + 1,
                    last_played = CURRENT_TIMESTAMP
                ''', (user_id, guild_id, song_title, song_url, artist))
                m_conn.commit()
        except Exception as e:
            logger.error(f"[DatabaseCog] 재생 기록 추가 오류: {e}")

    def get_play_history(self, user_id: str, guild_id: str, limit: int = 10) -> list:
        try:
            with self.get_master_conn() as m_conn:
                result = m_conn.execute('''
                    SELECT artist, song_title, song_url, play_count, last_played
                    FROM play_history
                    WHERE user_id=? AND guild_id=?
                    ORDER BY play_count DESC
                    LIMIT ?
                ''', (user_id, guild_id, limit)).fetchall()
                return [
                    {'artist': row[0] or 'Unknown', 'title': row[1], 'url': row[2],
                     'play_count': row[3], 'last_played': row[4]}
                    for row in result
                ]
        except Exception as e:
            logger.error(f"[DatabaseCog] 재생 기록 조회 오류: {e}")
            return []


async def setup(bot):
    await bot.add_cog(DatabaseCog(bot))
