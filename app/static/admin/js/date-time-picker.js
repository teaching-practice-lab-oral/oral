class DateTimePicker {
  constructor(hiddenInputId, { placeholder = '選擇日期時間' } = {}) {
    this.el = document.getElementById(hiddenInputId);
    this.viewYear = new Date().getFullYear();
    this.viewMonth = new Date().getMonth();
    this.tempDate = null;
    this.tempHour = 0;
    this.tempMin = 0;
    this._build(placeholder);
  }

  _build(placeholder) {
    const wrap = document.createElement('div');
    wrap.className = 'dtp-wrap';
    this.el.parentNode.insertBefore(wrap, this.el.nextSibling);

    const ig = document.createElement('div');
    ig.className = 'input-group';

    this.display = document.createElement('input');
    this.display.type = 'text';
    this.display.className = 'form-control dtp-display';
    this.display.placeholder = placeholder;
    this.display.readOnly = true;

    const calBtn = document.createElement('button');
    calBtn.type = 'button';
    calBtn.className = 'btn btn-outline-secondary';
    calBtn.innerHTML = '<i class="bi bi-calendar3"></i>';

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'btn btn-outline-secondary';
    clearBtn.innerHTML = '<i class="bi bi-x-lg"></i>';
    clearBtn.title = '清除';

    ig.append(this.display, calBtn, clearBtn);
    wrap.appendChild(ig);

    this.popup = document.createElement('div');
    this.popup.className = 'dtp-popup';
    this.popup.style.display = 'none';
    wrap.appendChild(this.popup);

    this.display.addEventListener('click', e => { e.stopPropagation(); this._toggle(); });
    calBtn.addEventListener('click', e => { e.stopPropagation(); this._toggle(); });
    clearBtn.addEventListener('click', e => { e.stopPropagation(); this.clear(); });
    this.popup.addEventListener('click', e => e.stopPropagation());
  }

  _toggle() {
    if (this.popup.style.display === 'none') this._open(); else this._close();
  }

  _open() {
    DateTimePicker.closeAll();
    const val = this.el.value;
    if (val) {
      const [dp, tp = '00:00'] = val.split('T');
      const [y, m, d] = dp.split('-').map(Number);
      const [h, mn] = tp.split(':').map(Number);
      this.tempDate = { year: y, month: m - 1, day: d };
      this.viewYear = y;
      this.viewMonth = m - 1;
      this.tempHour = h;
      this.tempMin = mn;
    } else {
      this.tempDate = null;
      const now = new Date();
      this.viewYear = now.getFullYear();
      this.viewMonth = now.getMonth();
      this.tempHour = 0;
      this.tempMin = 0;
    }
    this._render();
    this.popup.style.display = 'block';
  }

  _close() {
    this.popup.style.display = 'none';
  }

  _render() {
    const y = this.viewYear;
    const m = this.viewMonth;
    const firstDay = new Date(y, m, 1).getDay();
    const dim = new Date(y, m + 1, 0).getDate();
    const now = new Date();
    const [ty, tm, td] = [now.getFullYear(), now.getMonth(), now.getDate()];
    const months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];

    let days = '';
    for (let i = 0; i < firstDay; i++) days += '<span class="dtp-day other"></span>';
    for (let d = 1; d <= dim; d++) {
      const isSel = this.tempDate && this.tempDate.year === y && this.tempDate.month === m && this.tempDate.day === d;
      const isTod = y === ty && m === tm && d === td;
      const cls = 'dtp-day' + (isSel ? ' selected' : isTod ? ' today' : '');
      days += `<span class="${cls}" data-day="${d}">${d}</span>`;
    }
    const rem = (firstDay + dim) % 7;
    if (rem) for (let i = 0; i < 7 - rem; i++) days += '<span class="dtp-day other"></span>';

    const hrOpts = Array.from({ length: 24 }, (_, i) =>
      `<option value="${i}"${this.tempHour === i ? ' selected' : ''}>${String(i).padStart(2, '0')}</option>`
    ).join('');
    const mnOpts = Array.from({ length: 60 }, (_, i) =>
      `<option value="${i}"${this.tempMin === i ? ' selected' : ''}>${String(i).padStart(2, '0')}</option>`
    ).join('');

    this.popup.innerHTML = `
      <div class="dtp-header">
        <button type="button" class="dtp-nav" data-dir="-1">&#8249;</button>
        <span class="dtp-month-year">${y}年${months[m]}</span>
        <button type="button" class="dtp-nav" data-dir="1">&#8250;</button>
      </div>
      <div class="dtp-weekdays"><span>日</span><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span></div>
      <div class="dtp-days">${days}</div>
      <div class="dtp-time">
        <span class="dtp-time-label"><i class="bi bi-clock me-1"></i>時間</span>
        <select class="dtp-hour">${hrOpts}</select>
        <span class="dtp-colon">:</span>
        <select class="dtp-min">${mnOpts}</select>
      </div>
      <div class="dtp-actions">
        <button type="button" class="dtp-btn-clear">清除</button>
        <button type="button" class="dtp-btn-confirm">確定</button>
      </div>`;

    this.popup.querySelectorAll('.dtp-nav').forEach(btn => {
      btn.addEventListener('click', () => {
        this.viewMonth += parseInt(btn.dataset.dir);
        if (this.viewMonth < 0) {
          this.viewMonth = 11;
          this.viewYear--;
        }
        if (this.viewMonth > 11) {
          this.viewMonth = 0;
          this.viewYear++;
        }
        this._render();
      });
    });
    this.popup.querySelectorAll('.dtp-day:not(.other)').forEach(span => {
      span.addEventListener('click', () => {
        this.tempDate = { year: this.viewYear, month: this.viewMonth, day: parseInt(span.dataset.day) };
        this._render();
      });
    });
    this.popup.querySelector('.dtp-hour').addEventListener('change', e => { this.tempHour = parseInt(e.target.value); });
    this.popup.querySelector('.dtp-min').addEventListener('change', e => { this.tempMin = parseInt(e.target.value); });
    this.popup.querySelector('.dtp-btn-clear').addEventListener('click', () => this.clear());
    this.popup.querySelector('.dtp-btn-confirm').addEventListener('click', () => this.confirm());
  }

  confirm() {
    if (!this.tempDate) {
      this.clear();
      return;
    }
    const { year, month, day } = this.tempDate;
    const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}T${String(this.tempHour).padStart(2, '0')}:${String(this.tempMin).padStart(2, '0')}`;
    this.el.value = iso;
    this.display.value = this._fmt(year, month + 1, day, this.tempHour, this.tempMin);
    this._close();
  }

  clear() {
    this.el.value = '';
    this.display.value = '';
    this.tempDate = null;
    this._close();
  }

  syncFromHidden() {
    const val = this.el.value;
    if (!val) {
      this.display.value = '';
      return;
    }
    const [dp, tp = '00:00'] = val.split('T');
    const [y, m, d] = dp.split('-').map(Number);
    const [h, mn] = tp.split(':').map(Number);
    this.display.value = this._fmt(y, m, d, h, mn);
  }

  _fmt(y, m, d, h, mn) {
    return `${y}/${String(m).padStart(2, '0')}/${String(d).padStart(2, '0')} ${String(h).padStart(2, '0')}:${String(mn).padStart(2, '0')}`;
  }

  static closeAll() {
    document.querySelectorAll('.dtp-popup').forEach(p => { p.style.display = 'none'; });
  }
}

window.DateTimePicker = DateTimePicker;
