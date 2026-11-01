/* Local writing workbench: plans, evidence and scoped edits. No model/network service. */
(() => {
  const el = (id) => document.getElementById(id);
  let version = null, active = "", changed = false, ticket = 0, range = null;
  const fields = ["reader", "question", "conclusion", "new_information", "exclude", "facts", "structure"];
  const mark = () => {
    changed = true;
    el("saveState").textContent = "有未保存修改";
    preflight = null;
    el("btnPublish").disabled = true;
    el("repeatResults").replaceChildren();
  };
  function brief() {
    const result = { title: el("titleInput").value };
    for (const key of fields) result[key] = el("brief_" + key).value;
    result.exclude = result.exclude.split("\n").map(s => s.trim()).filter(Boolean);
    result.facts = result.facts.split("\n").filter(s => s.trim()).map(line => {
      const at = line.lastIndexOf(" | ");
      return { claim: at < 0 ? line.trim() : line.slice(0, at).trim(),
               source: at < 0 ? "" : line.slice(at + 3).trim() };
    });
    return result;
  }
  async function request(body) {
    const response = await fetch("/api/editorial", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({file: active, brief: brief(), ...body})
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "写作操作失败");
    return data;
  }
  async function load(name) {
    if (changed && !confirm("当前稿件有未保存修改，切换会丢失这些修改，仍要切换吗？")) {
      el("draftSel").value = active;
      return;
    }
    const current = ++ticket;
    el("btnSaveDraft").disabled = true;
    try {
      const response = await fetch("/api/editorial?file=" + encodeURIComponent(name));
      const data = await response.json();
      if (current !== ticket) return;
      if (!data.ok) throw new Error(data.error);
      active = name; version = data.revision; changed = false; range = null;
      el("draftName").value = name;
      el("articleBody").value = data.markdown;
      el("brief_structure").replaceChildren(...data.structures.map(s => {
        const option = document.createElement("option"); option.value = s.id;
        option.textContent = s.name; return option;
      }));
      for (const key of fields) {
        let value = data.brief[key] || "";
        if (key === "facts") value = (value || []).map(f => f.claim + " | " + f.source).join("\n");
        if (key === "exclude") value = (value || []).join("\n");
        el("brief_" + key).value = value;
      }
      el("titleInput").value = data.title || "";
      el("saveState").textContent = "已读取 · 修改后保存到本地";
      el("planResults").replaceChildren();
      el("rewritePrompt").value = ""; el("replacement").value = "";
    } catch (error) { version = null; toast(error.message, "bad"); }
    finally { if (current === ticket) el("btnSaveDraft").disabled = version === null; }
  }
  async function save() {
    if (!active || version === null) throw new Error("先读取或新建稿件");
    const data = await request({action: "save", markdown: el("articleBody").value, revision: version});
    version = data.revision; changed = false;
    let option = [...el("draftSel").options].find(o => o.value === active);
    if (!option) { option = new Option(active, active); el("draftSel").add(option); }
    option.dataset.title = el("titleInput").value;
    el("draftSel").value = active;
    el("saveState").textContent = "已保存到本地";
    return true;
  }
  async function plans() {
    const data = await request({action: "plan"});
    el("planResults").replaceChildren();
    for (const plan of data.plans) {
      const box = document.createElement("div"); box.className = "outline-option";
      const title = document.createElement("strong"); title.textContent = plan.name;
      const list = document.createElement("ol");
      for (const section of plan.sections) { const li = document.createElement("li"); li.textContent = section; list.append(li); }
      const note = document.createElement("p"); note.className = "hint"; note.textContent = plan.note;
      const button = document.createElement("button"); button.textContent = "采用此结构";
      button.onclick = () => {el("brief_structure").value = plan.id; mark(); toast("已选结构，正文保留");};
      box.append(title, list, note, button);
      for (const card of plan.references || []) {
        const example = document.createElement("p"); example.className = "hint";
        example.textContent = "已学习：" + card.reader_question + "；适用：" + card.applicable_when;
        box.append(example);
      }
      el("planResults").append(box);
    }
  }
  async function capture() {
    const input = el("articleBody");
    range = {start: input.selectionStart, end: input.selectionEnd, original: input.value};
    const selected = input.value.slice(range.start, range.end);
    const data = await request({action: "rewrite", selected, instruction: el("rewriteInstruction").value});
    el("rewritePrompt").value = data.prompt;
    el("replacement").value = selected;
    toast("已生成改写任务；可交给当前 AI，也可直接在下方修改选段");
  }
  function apply() {
    if (!range || el("articleBody").value !== range.original) throw new Error("正文已变化，请重新选段");
    el("articleBody").value = range.original.slice(0, range.start) + el("replacement").value + range.original.slice(range.end);
    range = null; mark(); toast("已替换选段，其余正文保留；保存后体检");
  }
  function renderReview(report) {
    const target = el("repeatResults"); target.replaceChildren();
    const note = document.createElement("p"); note.className = "hint";
    note.textContent = report.method + " · 已对照 " + report.history_count + " 篇已发文章"; target.append(note);
    for (const match of report.matches) {
      const box = document.createElement("details");
      const summary = document.createElement("summary"); summary.textContent = "与《" + match.title + "》的重复线索"; box.append(summary);
      for (const p of match.repeated_paragraphs) {
        const text = document.createElement("p"); text.textContent = "本稿：" + p.text;
        const old = document.createElement("blockquote"); old.textContent = "旧文：" + p.previous;
        box.append(text, old);
      }
      for (const fact of match.reused_facts) { const p = document.createElement("p"); p.textContent = "复用事实：" + fact; box.append(p); }
      if (match.same_claim) {const p = document.createElement("p"); p.textContent = "核心问题与结论近似，检查新增信息是否成立。"; box.append(p);}
      target.append(box);
    }
  }
  const run = (fn) => async () => { try { await fn(); } catch (error) { toast(error.message, "bad"); } };
  for (const id of fields.map(k => "brief_" + k).concat(["articleBody", "titleInput", "topicInput"])) el(id).addEventListener("input", mark);
  el("btnSaveDraft").onclick = run(async () => {await save(); toast("稿件与选题卡已保存");});
  el("btnPlans").onclick = run(plans);
  el("btnCapture").onclick = run(capture);
  el("btnApplyParagraph").onclick = run(apply);
  el("btnNewDraft").onclick = run(async () => {
    const name = el("draftName").value.trim();
    await load(name);
  });
  window.addEventListener("beforeunload", event => {if (changed) {event.preventDefault(); event.returnValue = "";}});
  window.editorialWorkbench = {load, save, renderReview};
})();
