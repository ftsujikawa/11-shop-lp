'use strict';

/* =========================================================
 * 祝日の計算（外部ライブラリなし）
 * 2020年以降の「国民の祝日に関する法律」に基づく。
 * 春分・秋分の日は計算式による近似で、正式には前年2月の官報で確定する。
 * ========================================================= */

const pad = (n) => String(n).padStart(2, '0');
const dateKey = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;

/** m月の第n月曜日の日付 */
function nthMonday(year, month, n) {
  const firstDow = new Date(year, month - 1, 1).getDay();
  const firstMonday = 1 + ((8 - firstDow) % 7);
  return firstMonday + (n - 1) * 7;
}

function vernalEquinoxDay(year) {
  return Math.floor(20.8431 + 0.242194 * (year - 1980) - Math.floor((year - 1980) / 4));
}

function autumnalEquinoxDay(year) {
  return Math.floor(23.2488 + 0.242194 * (year - 1980) - Math.floor((year - 1980) / 4));
}

/** その年の祝日を Map<"YYYY-MM-DD", 名前> で返す（振替休日・国民の休日を含む） */
function getHolidays(year) {
  const base = [
    [1, 1, '元日'],
    [1, nthMonday(year, 1, 2), '成人の日'],
    [2, 11, '建国記念の日'],
    [2, 23, '天皇誕生日'],
    [3, vernalEquinoxDay(year), '春分の日'],
    [4, 29, '昭和の日'],
    [5, 3, '憲法記念日'],
    [5, 4, 'みどりの日'],
    [5, 5, 'こどもの日'],
    [7, nthMonday(year, 7, 3), '海の日'],
    [8, 11, '山の日'],
    [9, nthMonday(year, 9, 3), '敬老の日'],
    [9, autumnalEquinoxDay(year), '秋分の日'],
    [10, nthMonday(year, 10, 2), 'スポーツの日'],
    [11, 3, '文化の日'],
    [11, 23, '勤労感謝の日'],
  ];

  const holidays = new Map();
  for (const [m, d, name] of base) holidays.set(dateKey(year, m, d), name);

  // 国民の休日：前後を祝日に挟まれた平日
  for (const [m, d] of base) {
    const next = new Date(year, m - 1, d + 2);
    const nextKey = dateKey(next.getFullYear(), next.getMonth() + 1, next.getDate());
    const between = new Date(year, m - 1, d + 1);
    const betweenKey = dateKey(between.getFullYear(), between.getMonth() + 1, between.getDate());
    if (holidays.has(nextKey) && !holidays.has(betweenKey) && between.getDay() !== 0) {
      holidays.set(betweenKey, '国民の休日');
    }
  }

  // 振替休日：祝日が日曜日のとき、その後の最初の祝日でない日
  for (const [key] of [...holidays]) {
    const [y, m, d] = key.split('-').map(Number);
    if (new Date(y, m - 1, d).getDay() !== 0) continue;
    let offset = 1;
    let sub;
    do {
      sub = new Date(y, m - 1, d + offset);
      offset += 1;
    } while (holidays.has(dateKey(sub.getFullYear(), sub.getMonth() + 1, sub.getDate())));
    holidays.set(dateKey(sub.getFullYear(), sub.getMonth() + 1, sub.getDate()), '振替休日');
  }

  return holidays;
}

// 祝日表は年ごとに1回だけ作る（1日ごとに作り直さない）
const holidayCache = new Map();

function holidayName(date) {
  const y = date.getFullYear();
  if (!holidayCache.has(y)) holidayCache.set(y, getHolidays(y));
  return holidayCache.get(y).get(dateKey(y, date.getMonth() + 1, date.getDate())) || null;
}

/* =========================================================
 * 定休日の判定（shop.md の内容）
 * - 毎週月曜日、第3火曜日
 * - 祝日の月曜日は営業し、翌火曜日が休み
 * ========================================================= */

function isClosed(date) {
  const dow = date.getDay();
  const isHoliday = holidayName(date) !== null;

  if (dow === 1) return !isHoliday; // 月曜：祝日なら営業

  if (dow === 2) {
    const day = date.getDate();
    if (day >= 15 && day <= 21) return true; // 第3火曜日
    const monday = new Date(date.getFullYear(), date.getMonth(), day - 1);
    if (holidayName(monday) !== null) return true; // 祝日の月曜の翌日
  }

  return false;
}

/* =========================================================
 * 今月の営業日カレンダー
 * ========================================================= */

function renderCalendar(today = new Date()) {
  const body = document.getElementById('calendar-body');
  const caption = document.getElementById('calendar-caption');
  if (!body || !caption) return;

  const year = today.getFullYear();
  const month = today.getMonth();
  const firstDow = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  // 行はいったん DocumentFragment に組み立て、最後に1回だけページへ反映する
  const fragment = document.createDocumentFragment();
  let row = document.createElement('tr');
  for (let i = 0; i < firstDow; i += 1) {
    const td = document.createElement('td');
    td.className = 'empty';
    row.appendChild(td);
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const date = new Date(year, month, day);
    const closed = isClosed(date);
    const holiday = holidayName(date);

    const td = document.createElement('td');
    if (closed) td.classList.add('closed');
    if (holiday) td.classList.add('holiday');
    if (day === today.getDate()) {
      td.classList.add('today');
      td.setAttribute('aria-current', 'date');
    }

    const num = document.createElement('span');
    num.className = 'day-num';
    num.textContent = day;
    td.appendChild(num);

    if (holiday) {
      // 祝日名は、スマホ幅ではセルに収まらないので「祝日」と短く表示する（CSS で切り替え）。
      // 正式名は画面に出さなくても読み上げられるよう残し、短い表記は読み上げない
      const label = document.createElement('span');
      label.className = 'day-label holiday-label';
      const full = document.createElement('span');
      full.className = 'label-full';
      full.textContent = holiday;
      const short = document.createElement('span');
      short.className = 'label-short';
      short.setAttribute('aria-hidden', 'true');
      short.textContent = '祝日';
      label.append(full, short);
      td.appendChild(label);
    }
    if (closed) {
      const label = document.createElement('span');
      label.className = 'day-label';
      label.textContent = '定休日';
      td.appendChild(label);
    }

    row.appendChild(td);

    if (date.getDay() === 6 || day === daysInMonth) {
      while (row.children.length < 7) {
        const empty = document.createElement('td');
        empty.className = 'empty';
        row.appendChild(empty);
      }
      fragment.appendChild(row);
      row = document.createElement('tr');
    }
  }

  caption.textContent = `${year}年${month + 1}月の営業日`;
  body.replaceChildren(fragment);
}

/* =========================================================
 * お問い合わせフォーム（入力チェックのみ・送信しない）
 * ========================================================= */

const MESSAGE_MAX = 500;

const validators = {
  name(value) {
    if (!value.trim()) return 'お名前を入力してください。';
    if (value.trim().length > 50) return 'お名前は50文字以内で入力してください。';
    return '';
  },
  email(value) {
    const v = value.trim();
    if (!v) return 'メールアドレスを入力してください。';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) return 'メールアドレスの形式が正しくありません（例：name@example.com）。';
    return '';
  },
  tel(value) {
    const v = value.trim();
    if (!v) return ''; // 任意
    if (!/^[0-9-]+$/.test(v)) return '電話番号は半角数字とハイフンで入力してください。';
    const digits = v.replace(/-/g, '');
    if (digits.length < 10 || digits.length > 11) return '電話番号は10〜11桁で入力してください。';
    return '';
  },
  message(value) {
    const v = value.trim();
    if (!v) return 'お問い合わせ内容を入力してください。';
    if (v.length > MESSAGE_MAX) return `お問い合わせ内容は${MESSAGE_MAX}文字以内で入力してください。`;
    return '';
  },
};

function validateField(input) {
  const check = validators[input.name];
  if (!check) return true;
  const message = check(input.value);
  const error = document.getElementById(`${input.id}-error`);
  if (error) error.textContent = message;
  input.setAttribute('aria-invalid', message ? 'true' : 'false');
  return message === '';
}

function updateCharCount(textarea) {
  const counter = document.getElementById('message-count');
  if (!counter) return;
  const length = textarea.value.trim().length;
  counter.textContent = `${length} / ${MESSAGE_MAX}文字`;
  counter.classList.toggle('over', length > MESSAGE_MAX);
}

function setupContactForm() {
  const form = document.getElementById('contact-form');
  if (!form) return;
  const result = document.getElementById('form-result');
  const fields = [...form.querySelectorAll('input, textarea')];

  for (const input of fields) {
    // 入力途中ではなく、一度離れてからチェックする
    input.addEventListener('blur', () => validateField(input));
    input.addEventListener('input', () => {
      if (input.getAttribute('aria-invalid') === 'true') validateField(input);
      if (input.name === 'message') updateCharCount(input);
      result.textContent = '';
    });
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault(); // 送信はしない

    const invalid = fields.filter((input) => !validateField(input));
    if (invalid.length > 0) {
      result.textContent = '入力内容に誤りがあります。赤字の項目をご確認ください。';
      invalid[0].focus();
      return;
    }

    result.textContent = '入力内容に問題はありません。（このページは見本のため、送信は行われません）';
  });
}

/* ========================================================= */

/* =========================================================
 * 固定ヘッダーの高さを CSS 変数に反映
 * （ページ内リンクの移動先やフォーカスした入力欄がヘッダーに隠れないように）
 * ========================================================= */

function trackHeaderHeight() {
  const header = document.querySelector('.site-header');
  if (!header) return;

  // scroll-padding-top を <html> に直接書く（CSS 変数を書き換えると、
  // 全要素のスタイル再計算が起きるため）。値が変わったときだけ書く。
  let last = -1;
  const apply = (height) => {
    const h = Math.round(height);
    if (h === last) return;
    last = h;
    document.documentElement.style.scrollPaddingTop = `${h + 8}px`;
  };

  if ('ResizeObserver' in window) {
    // ResizeObserver はレイアウト後に呼ばれ、初回も必ず通知される。
    // 大きさは entry から受け取るので、offsetHeight でレイアウトを強制しない。
    new ResizeObserver(([entry]) => {
      const box = entry.borderBoxSize && entry.borderBoxSize[0];
      apply(box ? box.blockSize : entry.target.offsetHeight);
    }).observe(header);
  } else {
    const measure = () => requestAnimationFrame(() => apply(header.offsetHeight));
    measure();
    window.addEventListener('resize', measure);
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    // DOM を書き換える処理を先に済ませ、レイアウトの読み取りは後に回す
    renderCalendar();
    setupContactForm();
    trackHeaderHeight();
  });
}

/* build:remove-start — Node での動作確認用。ブラウザでは使わないので script.min.js からは削除される */
if (typeof module !== 'undefined') {
  module.exports = { getHolidays, isClosed, holidayName };
}
/* build:remove-end */
