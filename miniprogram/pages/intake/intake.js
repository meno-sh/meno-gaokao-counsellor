const api = require("../../utils/api.js");
Page({
  data: {
    options: [{label:"",note:""},{label:"",note:""}],
    conf: 50,
    w: { money:33, interest:34, influence:33 },
    destOpts: ["升学","就业","出国","还没想好"],
    dest: "还没想好",
    freeText: "",
    busy: false, err: "",
    recording: false, vstat: "", transcript: "",
    step: 1,
    chat1: [], chat2: [], chat3: [], chat4: [], draft1: "", draft2: "", draft3: "", draft4: "",
    macroText: ""
  },
  onLoad() {
    const rec = wx.getRecorderManager(); this._rec = rec;
    rec.onStop((res)=> this.handleAudio(res.tempFilePath));
    rec.onError(()=> this.setData({ recording:false, vstat:"录音出错,可手动填" }));
  },
  toggleRec() {
    if (this.data.recording) { this._rec.stop(); this.setData({ recording:false, vstat:"识别中…" }); return; }
    wx.authorize({ scope:"scope.record", success: ()=>{ this._rec.start({ format:"mp3", duration:120000 }); this.setData({ recording:true, vstat:"录音中…(再点停止)", err:"" }); }, fail: ()=> this.setData({ vstat:"需要麦克风权限,或手动填" }) });
  },
  handleAudio(path) {
    try {
      const b64 = wx.getFileSystemManager().readFileSync(path, "base64");
      this.setData({ vstat:"识别中…" });
      const api2 = require("../../utils/api.js");
      api2.voiceIntake(b64).then((r)=>{
        this.setData({ transcript: r.transcript || "" });
        const k = r.intake || {};
        const opts = (k.candidates||[]).map(c=>({ label: c.label||c.raw||"", note:"" }));
        this.setData({
          options: opts.length>=2 ? opts : this.data.options,
          conf: (k.confidence_initial!=null? k.confidence_initial : this.data.conf),
          w: k.value_weights || this.data.w,
          dest: (k.destination_pref && k.destination_pref[0]) || this.data.dest,
          freeText: k.free_text || this.data.freeText,
          vstat: opts.length>=2 ? "填好了,看一眼下面、可改,然后开始 ↓" : "没太听清候选,请手动填或再说一次"
        });
      }).catch((e)=> this.setData({ vstat:"识别失败:"+(e.message||"")+" ,可手动填" }));
    } catch(e) { this.setData({ vstat:"读取录音失败,可手动填" }); }
  },
  addOpt() { this.setData({ options: this.data.options.concat([{label:"",note:""}]) }); },
  removeOpt(e) { const i=e.currentTarget.dataset.i; const o=this.data.options.slice(); if(o.length>2){o.splice(i,1); this.setData({options:o});} },
  onLabel(e){ const o=this.data.options.slice(); o[e.currentTarget.dataset.i].label=e.detail.value; this.setData({options:o}); },
  onNote(e){ const o=this.data.options.slice(); o[e.currentTarget.dataset.i].note=e.detail.value; this.setData({options:o}); },
  onConf(e){ this.setData({ conf: e.detail.value }); },
  onW(e){ const k=e.currentTarget.dataset.k; const w=Object.assign({},this.data.w); w[k]=e.detail.value; this.setData({w}); },
  pickDest(e){ this.setData({ dest: e.currentTarget.dataset.d }); },
  onFree(e){ this.setData({ freeText: e.detail.value }); },
  onMacro(e){ this.setData({ macroText: e.detail.value }); },
  next() { if (this.data.step < 4) this.setData({ step: this.data.step + 1 }); wx.pageScrollTo({ scrollTop: 0, duration: 200 }); },
  prev() { if (this.data.step > 1) this.setData({ step: this.data.step - 1 }); wx.pageScrollTo({ scrollTop: 0, duration: 200 }); },
  onChatInput(e) { this.setData({ ["draft" + e.currentTarget.dataset.n]: e.detail.value }); },
  async sendChat(e) {
    const n = e.currentTarget.dataset.n; const key = "chat" + n;
    const msg = (this.data["draft" + n] || "").trim(); if (!msg) return;
    let log = this.data[key].slice();
    if (log.filter(m => m.role === "h").length >= 6) { log.push({ role: "a", text: "(这一步聊得差不多啦,去下一步吧)" }); this.setData({ [key]: log }); return; }
    log.push({ role: "h", text: msg }); this.setData({ [key]: log, ["draft" + n]: "" });
    const state = {
      candidates: this.data.options.map(o => (o.label || "").trim()).filter(Boolean),
      free_text: (this.data.freeText + (this.data.macroText ? ("\n【宏观】" + this.data.macroText) : "")), confidence: Number(this.data.conf),
      value_weights: this.data.w, destination_pref: [this.data.dest],
    };
    const history = this.data[key].map(m => [m.role, m.text]);
    try {
      const r = await api.intakeChat({ message: msg, page: String(n), state, history, lang: "cn" });
      const log2 = this.data[key].slice(); log2.push({ role: "a", text: (r.reply || "(没回应,稍后再试)") }); this.setData({ [key]: log2 });
    } catch (err) {
      const log2 = this.data[key].slice(); log2.push({ role: "a", text: "(对话暂时连不上)" }); this.setData({ [key]: log2 });
    }
  },
  async start() {
    const opts = this.data.options.map(o=>({label:(o.label||"").trim(), note:(o.note||"").trim()})).filter(o=>o.label);
    if (opts.length < 2) { this.setData({ err: "至少填 2 个候选" }); return; }
    this.setData({ busy:true, err:"" });
    try {
      const body = {
        options: opts,
        free_text: (this.data.freeText.trim() + (this.data.macroText.trim() ? ("\n\n【对未来的宏观思考】" + this.data.macroText.trim()) : "")).trim(),
        quiz: {},
        destination_pref: [this.data.dest],
        confidence_initial: Number(this.data.conf),
        value_weights: this.data.w,
        lang: "cn"
      };
      const r = await api.rankStart(body);
      const app = getApp();
      app.globalData.sid = r.sid;
      app.globalData.intake = r;            // { sid, narrative, stage }
      app.globalData.confInitial = Number(this.data.conf);
      wx.navigateTo({ url: "/pages/game/game" });
    } catch (e) {
      this.setData({ err: e.message || "出错了，请重试" });
    } finally {
      this.setData({ busy:false });
    }
  }
});