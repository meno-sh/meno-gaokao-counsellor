const api = require("../../utils/api.js");
const MP_CAP = 7;  // 小程序端限制每局站数(API 默认更长)
Page({
  data: { stage:{}, order:[], conf:60, chat:[], draft:"", turnsLeft:3, showSrc:false, busy:false, err:"", _t0:0, isLast:false },
  onLoad() {
    const app = getApp();
    const r = app.globalData.intake || {};
    const st = r.stage || {};
    this.setData({
      stage: st,
      order: (st.order || []).slice(),
      conf: app.globalData.confInitial || 60,
      turnsLeft: 3, _t0: Date.now(),
      isLast: !!(st.last || (st.stage||0) >= MP_CAP)
    });
  },
  toggleSrc(){ this.setData({ showSrc: !this.data.showSrc }); },
  onConf(e){ this.setData({ conf: e.detail.value }); },
  onDraft(e){ this.setData({ draft: e.detail.value }); },
  _applyStage(st) {
    this.setData({ stage: st, order: (st.order||[]).slice(), chat: [], draft:"", turnsLeft: 3, showSrc:false, conf: this.data.conf, _t0: Date.now(), isLast: !!(st.last || (st.stage||0) >= MP_CAP) });
  },
  async reorder(order) {
    const sid = getApp().globalData.sid;
    this.setData({ order });
    try { await api.rankReorder(sid, order); } catch(e) { /* 排序失败不阻塞 */ }
  },
  moveUp(e){ const i=e.currentTarget.dataset.i; if(i<=0)return; const o=this.data.order.slice(); [o[i-1],o[i]]=[o[i],o[i-1]]; this.reorder(o); },
  moveDown(e){ const i=e.currentTarget.dataset.i; const o=this.data.order.slice(); if(i>=o.length-1)return; [o[i+1],o[i]]=[o[i],o[i+1]]; this.reorder(o); },
  async send() {
    const msg=(this.data.draft||"").trim(); if(!msg) return;
    const sid=getApp().globalData.sid;
    this.setData({ chat: this.data.chat.concat([{role:"me",text:msg}]), draft:"" });
    try {
      const r = await api.rankChat(sid, msg, "scene");
      const tl = (r.turns_left!=null ? r.turns_left : this.data.turnsLeft-1);
      if (tl <= 0) {
        // cap reached: drop the AI's dangling (unanswerable) question; clean close
        this.setData({ chat: this.data.chat.concat([{role:"sys",text:"(本环节对话已结束)"}]), turnsLeft: 0 });
      } else {
        this.setData({ chat: this.data.chat.concat([{role:"ai",text:r.reply}]), turnsLeft: tl });
      }
    } catch(e) {
      if ((e.message||"").indexOf("limit")>=0) this.setData({ turnsLeft: 0 });
      else this.setData({ err: e.message });
    }
  },
  async next() {
    const sid=getApp().globalData.sid;
    this.setData({ busy:true, err:"" });
    try {
      const dwell = Date.now() - this.data._t0;
      if (this.data.isLast) {   // 到达小程序站数上限(或 API 最后一站)-> 结束
        const re = await api.rankNext(sid, { end:1, confidence: Number(this.data.conf), order: this.data.order, dwell_ms: dwell });
        getApp().globalData.ending = re.ending; wx.redirectTo({ url:"/pages/ending/ending" }); return;
      }
      const r = await api.rankNext(sid, { confidence: Number(this.data.conf), order: this.data.order, dwell_ms: dwell });
      if (r.phase === "ending" || r.ending) { getApp().globalData.ending = r.ending; wx.redirectTo({ url:"/pages/ending/ending" }); return; }
      this._applyStage(r.stage);
    } catch(e) { this.setData({ err: e.message }); }
    finally { this.setData({ busy:false }); }
  },
  async endNow() {
    const sid=getApp().globalData.sid;
    this.setData({ busy:true, err:"" });
    try {
      const r = await api.rankNext(sid, { end:1, confidence: Number(this.data.conf) });
      getApp().globalData.ending = r.ending; wx.redirectTo({ url:"/pages/ending/ending" });
    } catch(e){ this.setData({ err:e.message, busy:false }); }
  }
});