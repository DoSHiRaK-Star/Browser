# text_browser.py
import re
import threading
import tkinter as tk
from tkinter import ttk
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen, Request


class HtmlToText(HTMLParser):
    """Превращает HTML в плоский текст, а <a href> — в маркеры \x00N\x00."""
    BLOCK = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
             'section', 'article', 'header', 'footer', 'nav', 'ul', 'ol',
             'table', 'blockquote', 'pre', 'hr'}
    SKIP = {'script', 'style', 'head', 'noscript'}

    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._out = []
        self._skip = 0
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        d = dict(attrs)
        if tag in self.BLOCK:
            self._out.append('\n')
        if tag == 'a' and d.get('href'):
            url = urljoin(self.base_url, d['href'])
            if urlparse(url).scheme in ('http', 'https'):
                self.links.append(url)
                self._out.append('\x00%d\x00' % len(self.links))

    def handle_startendtag(self, tag, attrs):
        if self._skip or tag in self.SKIP:
            return
        if tag in self.BLOCK:
            self._out.append('\n')

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        if tag in self.BLOCK:
            self._out.append('\n')

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if text:
            self._out.append(text + ' ')

    def result(self):
        text = ''.join(self._out)
        text = re.sub(r'[ \t\f\v]+', ' ', text)
        text = re.sub(r' *\n *', '\n', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


def decode_html(raw: bytes, headers) -> str:
    charset = headers.get_content_charset()
    if not charset:
        m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096], re.I)
        if m:
            charset = m.group(1).decode('ascii', 'ignore')
    return raw.decode(charset or 'utf-8', errors='replace')


class TextBrowser(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Текстовый браузер')
        self.geometry('950x700')
        self.links = []          # список URL, индекс+1 = номер ссылки
        self.history = []
        self._build_ui()

    # ---------- интерфейс ----------
    def _build_ui(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill='x')

        self.url_var = tk.StringVar(value='https://example.com')
        entry = ttk.Entry(top, textvariable=self.url_var)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda e: self.go())

        ttk.Button(top, text='Назад', command=self.back).pack(side='left', padx=4)
        ttk.Button(top, text='Перейти', command=self.go).pack(side='left')

        self.status = tk.StringVar(value='Готово')
        ttk.Label(self, textvariable=self.status, anchor='w',
                  padding=(8, 0)).pack(fill='x')

        self.text = tk.Text(self, wrap='word', font=('Consolas', 11),
                            padx=10, pady=10)
        sb = ttk.Scrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.text.pack(fill='both', expand=True)

        self.text.tag_configure('link', foreground='#0645ad', underline=True)
        self.text.tag_bind('link', '<Button-1>', self._on_link_click)
        self.text.tag_bind('link', '<Enter>',
                           lambda e: self.text.config(cursor='hand2'))
        self.text.tag_bind('link', '<Leave>',
                           lambda e: self.text.config(cursor=''))

        bottom = ttk.Frame(self, padding=6)
        bottom.pack(fill='x')
        ttk.Label(bottom, text='Номер ссылки:').pack(side='left')
        self.num_var = tk.StringVar()
        ne = ttk.Entry(bottom, textvariable=self.num_var, width=8)
        ne.pack(side='left', padx=4)
        ne.bind('<Return>', lambda e: self.open_by_number())
        ttk.Button(bottom, text='Открыть',
                   command=self.open_by_number).pack(side='left')

    # ---------- навигация ----------
    def go(self):
        url = self.url_var.get().strip()
        if not url:
            return
        if not urlparse(url).scheme:
            url = 'https://' + url
        self.open_url(url)

    def open_url(self, url):
        self.status.set(f'Загрузка {url} …')
        threading.Thread(target=self._fetch, args=(url,), daemon=True).start()

    def _fetch(self, url):
        try:
            req = Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (TextBrowser)',
                'Accept': 'text/html,application/xhtml+xml',
            })
            with urlopen(req, timeout=15) as resp:
                raw = resp.read()
                html = decode_html(raw, resp.headers)
                final_url = resp.geturl()

            parser = HtmlToText(final_url)
            parser.feed(html)
            self.after(0, self._show, final_url,
                       parser.result(), parser.links)
        except Exception as exc:
            self.after(0, self._show_error, url, exc)

    def _show(self, url, text, links):
        self.history.append(url)
        self.url_var.set(url)
        self.render(text, links)
        self.status.set(f'{url} — найдено ссылок: {len(links)}')

    def _show_error(self, url, exc):
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('end', f'Не удалось загрузить {url}\n\n{exc}')
        self.text.config(state='disabled')
        self.status.set('Ошибка загрузки')

    def back(self):
        if len(self.history) > 1:
            self.history.pop()
            self.open_url(self.history.pop())

    # ---------- отрисовка ----------
    def render(self, raw, links):
        self.text.config(state='normal')
        self.text.delete('1.0', 'end')
        self.links = links

        parts = re.split(r'\x00(\d+)\x00', raw)
        for i, part in enumerate(parts):
            if i % 2 == 0:
                self.text.insert('end', part)
            else:
                n = int(part)
                self.text.insert('end', f'[{n}]', ('link', f'lnk{n}'))

        self.text.config(state='disabled')
        self.text.yview_moveto(0)

    def _on_link_click(self, event):
        idx = self.text.index(f'@{event.x},{event.y}')
        for tag in self.text.tag_names(idx):
            if tag.startswith('lnk') and tag[3:].isdigit():
                n = int(tag[3:])
                if 1 <= n <= len(self.links):
                    self.open_url(self.links[n - 1])
                return

    def open_by_number(self):
        try:
            n = int(self.num_var.get())
            url = self.links[n - 1]
        except (ValueError, IndexError):
            self.status.set('Такой ссылки нет')
            return
        self.num_var.set('')
        self.open_url(url)


if __name__ == '__main__':
    TextBrowser().mainloop()