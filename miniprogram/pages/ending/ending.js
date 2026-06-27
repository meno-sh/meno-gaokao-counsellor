const api = require("../../utils/api.js");
Page({
  data: { e:{}, conf:70, busy:false, err:"" },
  onLoad(){ const e=getApp().globalData.ending||{}; this.setData({ e, conf: e.confidence_initial!=null? e.confidence_initial : 70 }); },
  onConf(e){ this.setData({ conf:e.detail.value }); },
  async finish(){
    const sid=getApp().globalData.sid;
    this.setData({ busy:true, err:"" });
    try {
      await api.rankEnd(sid, { confidence_final: Number(this.data.conf) });
      const r = await api.rankReport(sid);
      getApp().globalData.report = r.report || "";
      wx.redirectTo({ url:"/pages/report/report" });
    } catch(e){ this.setData({ err:e.message, busy:false }); }
  }
});