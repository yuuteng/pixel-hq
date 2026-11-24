// The focused Claude session's own PRs, one tab per Jira ticket, with their Stash review state and CI, and the markdown files it wrote.

import { View, div, svg } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { focused, exec, appHome, theme, checking, shared, setShared } from "herdr";

const CI = {
  failed: ["✕", "#f38ba8", "CI failed · click to open the build"],
  inprogress: ["●", "#f9e2af", "CI running · click to open the build"],
  successful: ["✓", "#a6e3a1", "CI passed"],
  none: ["–", null, "No CI build on the last commit"],
};
const HELPER = () => `${appHome()}/mods/company-prs/sessions.py`;
const open = (url) => exec("open", [url]).catch(() => null);
const TAB = "pixel-hq.ticket-tab";
const tabId = (k) => k ?? "other";
const HIDDEN = "pixel-hq.ticket-hidden";
const stored = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key) ?? "null") ?? fallback; } catch { return fallback; } };

function tone(t, pr) {
  if (pr.state === "MERGED") return "#cba6f7";
  if (pr.state === "DECLINED") return t.dim;
  if (pr.label.startsWith("needs work")) return "#f38ba8";
  if (pr.label.startsWith("approved")) return "#a6e3a1";
  if (pr.label.startsWith("commented")) return "#f9e2af";
  if (pr.draft) return t.dim;
  return "#89b4fa";
}

function shortLabel(pr) {
  if (pr.state === "MERGED") return "merged";
  if (pr.state === "DECLINED") return "declined";
  if (pr.draft && !/^(needs|approved|commented)/.test(pr.label)) return "draft";
  return pr.label.replace(/ \(.*\)$/, "").replace(/ by .*$/, "").replace(/^waiting for review$/, "waiting");
}

export default class Prs extends View {
  init(_props, cx) {
    this.address = null;
    this.data = { session: null, ticket: null, prs: [], tickets: [] };
    this.branchOnly = localStorage.getItem("branchOnly") === "1";
    this.autoHide = localStorage.getItem("autoHide") !== "0";
    this.hiding = stored("hidden", {});
    this.showHidden = false;
    this.publish();
    this.loading = false;
    this.docs = [];
    if (checking()) return;
    cx.timer.every(1000, (cx) => this.follow(cx));
    cx.timer.every(20000, (cx) => this.load(cx));
    this.follow(cx);
  }

  follow(cx) {
    const f = focused();
    const address = f?.agent ?? f?.terminal ?? null;
    if (!address || address === this.address) return;
    this.address = address;
    this.docs = [];
    this.load(cx);
  }

  load(cx, fresh = false) {
    const address = this.address;
    if (!address) return;
    const seq = this.seq = (this.seq ?? 0) + 1;
    this.loadDocs(cx);
    this.loading = true;
    cx.notify();
    cx.spawn(async (cx) => {
      const r = await exec("python3", ["-I", HELPER(), "prs", address, ...(fresh ? ["--fresh"] : [])], { timeout: 60000 }).catch(() => null);
      if (address !== this.address || seq !== this.seq) return;
      this.loading = false;
      if (r?.code === 0) {
        try { this.data = JSON.parse(r.stdout); } catch {}
        this.sync();
      }
      cx.notify();
    });
  }

  loadDocs(cx) {
    const address = this.address;
    cx.spawn(async (cx) => {
      const r = await exec("python3", ["-I", HELPER(), "docs", address]).catch(() => null);
      if (address !== this.address || r?.code !== 0) return;
      let docs = [];
      try { docs = JSON.parse(r.stdout).docs; } catch { return; }
      if (JSON.stringify(docs) === JSON.stringify(this.docs)) return;
      this.docs = docs;
      cx.notify();
    });
  }

  // Tickets of the session that can be a tab: the ones with a PR, plus the ones with a branch only when the option is on.
  listed() {
    return (this.data.tickets ?? []).filter((k) => k.prs.length > 0 || this.branchOnly);
  }

  tabs() {
    const gone = new Set(this.gone(this.data.id));
    return this.listed().filter((k) => !gone.has(tabId(k.key)));
  }

  hiddenTabs() {
    const gone = new Set(this.gone(this.data.id));
    return this.listed().filter((k) => gone.has(tabId(k.key)));
  }

  // Tab ids hidden for a session: the closed ones, plus the finished ones while the option is on.
  gone(id) {
    const h = this.hiding[id];
    if (!h) return [];
    return [...new Set([...h.closed, ...(this.autoHide ? h.done.filter((k) => !h.kept.includes(k)) : [])])];
  }

  // Finished tickets of the focused session: done in Jira with every PR merged or declined. One tab always stays.
  sync() {
    const id = this.data.id;
    if (!id) return;
    const h = this.hiding[id] ?? { closed: [], kept: [], done: [] };
    const state = new Map(this.data.prs.map((p) => [p.key, p.state]));
    const done = this.listed().filter((k) => k.key && k.category === "Done" && k.prs.length > 0 && k.prs.every((p) => state.get(p) !== "OPEN"))
      .map((k) => k.key);
    const left = this.listed().filter((k) => !h.closed.includes(tabId(k.key)) && !(done.includes(k.key) && !h.kept.includes(k.key)));
    if (!left.length && done.length) done.shift();
    this.hiding = { ...this.hiding, [id]: { ...h, done } };
    this.store();
  }

  store() {
    localStorage.setItem("hidden", JSON.stringify(this.hiding));
    this.publish();
  }

  publish() {
    const next = Object.fromEntries(Object.keys(this.hiding).map((id) => [id, this.gone(id)]).filter(([, keys]) => keys.length));
    if (JSON.stringify(next) !== JSON.stringify(shared(HIDDEN) ?? {})) setShared(HIDDEN, next);
  }

  close(key, cx) {
    const id = this.data.id;
    if (!id) return;
    const h = this.hiding[id] ?? { closed: [], kept: [], done: [] };
    this.hiding = { ...this.hiding, [id]: { ...h, closed: [...new Set([...h.closed, tabId(key)])], kept: h.kept.filter((k) => k !== key) } };
    this.store();
    cx.notify();
  }

  restore(key, cx) {
    const id = this.data.id;
    const h = this.hiding[id];
    if (!h) return;
    this.hiding = { ...this.hiding, [id]: { ...h, closed: h.closed.filter((k) => k !== tabId(key)), kept: [...new Set([...h.kept, tabId(key)])] } };
    this.store();
    if (!this.hiddenTabs().length) this.showHidden = false;
    this.pick(key, cx);
    cx.notify();
  }

  current(tabs) {
    const picked = shared(TAB)?.[this.address];
    return tabs.find((k) => tabId(k.key) === picked) ?? tabs[0] ?? null;
  }

  pick(key, cx) {
    if (tabId(key) === shared(TAB)?.[this.address]) return;
    setShared(TAB, { ...(shared(TAB) ?? {}), [this.address]: tabId(key) });
    this.entering = true;
    cx.notify();
    cx.timer.after(40, (cx) => { this.entering = false; cx.notify(); });
  }

  // A PR title without the ticket key it starts with.
  untitled(title) {
    const keys = (this.data.config?.ticket_projects ?? []).join("|");
    return keys ? title.replace(new RegExp(`^(?:${keys})-\\d+[:\\s]+`, "i"), "") : title;
  }

  copyButton(t, prs) {
    const ready = prs.filter((p) => p.state === "OPEN" && !p.draft);
    const copied = this.copiedAt && Date.now() - this.copiedAt < 1500;
    return div().id("prs-copy").flex_none().px(5).rounded(4).text_size(11)
      .when(ready.length > 0, (el) => el.cursor_pointer().hover((h) => h.bg(t.hover).text_color(t.foreground))
        .tooltip(`Copy ${ready.length} PR${ready.length > 1 ? "s" : ""} open for review as Markdown`)
        .on_click((_e, cx) => {
          cx.write_to_clipboard(ready.map((p) => `* [${p.repo} #${p.number}](${p.url})`).join("\n"));
          this.copiedAt = Date.now();
          cx.notify();
          cx.timer.after(1600, (cx) => cx.notify());
        }))
      .when(!ready.length, (el) => el.opacity(0.4).tooltip("No PR open for review"))
      .child(copied ? "Copied" : "Copy");
  }

  render() {
    const t = theme();
    const { session } = this.data;
    const tabs = this.tabs();
    const cur = this.current(tabs);
    const ticket = cur?.key ? cur : null;
    const prs = cur ? this.data.prs.filter((p) => cur.prs.includes(p.key)) : [];
    const branchOnly = (this.data.tickets ?? []).filter((k) => !k.prs.length).length;
    const hiddenTabs = this.hiddenTabs();
    const repos = new Map();
    for (const p of prs) { if (!repos.has(p.repo)) repos.set(p.repo, []); repos.get(p.repo).push(p); }
    const tab = (k) => {
      const on = k === cur;
      return h_flex().id(`tab-${tabId(k.key)}`).relative().flex_none().h(28).px(10).gap(6).items_center().rounded(7).border_1()
        .border_color(k.prs.length ? t.chrome : t.dim).when(!k.prs.length, (el) => el.border_dashed())
        .text_size(11.5).font_semibold().text_color(on ? "#89b4fa" : t.muted)
        .cursor_pointer().hover((el) => el.bg(t.hover))
        .tooltip(k.key ? `${k.key}${k.summary ? `\n${k.summary}` : ""}` : "PRs without a ticket in their title")
        .on_click((_e, cx) => this.pick(k.key, cx))
        .child(div().id(`tab-on-${tabId(k.key)}`).absolute().left(0).top(0).size_full().rounded(7).bg(t.surface ?? t.hover)
          .opacity(on ? 1 : 0).transition("opacity", { duration: 220, easing: "ease-out" }))
        .child(div().relative().child(k.key ?? "other"))
        .child(div().relative().font_normal().text_color(t.dim).child(String(k.prs.length)))
        .child(div().id(`tab-close-${tabId(k.key)}`).relative().flex_none().w(16).h(16).rounded(4).flex().items_center().justify_center()
          .font_normal().text_size(12).text_color(t.dim).hover((el) => el.bg("#f38ba826").text_color("#f38ba8"))
          .tooltip("Hide this ticket").on_mouse_down("left", (_e, cx) => cx.stop_propagation())
          .on_click((_e, cx) => { cx.stop_propagation(); this.close(k.key, cx); }).child("×"));
    };
    const hiddenTab = (k) => h_flex().id(`tab-hidden-${tabId(k.key)}`).flex_none().h(28).px(10).gap(6).items_center().rounded(7).border_1()
      .border_dashed().border_color(t.dim).text_size(11.5).text_color(t.dim).cursor_pointer()
      .hover((el) => el.bg(t.hover).text_color(t.foreground))
      .tooltip(`Show ${k.key ?? "other"} again${k.summary ? `\n${k.summary}` : ""}`)
      .on_click((_e, cx) => this.restore(k.key, cx))
      .child(k.key ?? "other");
    const hiddenChip = hiddenTabs.length > 0 && div().id("tab-hidden").flex_none().h(28).px(8).rounded(7).flex().items_center()
      .text_size(11).text_color(this.showHidden ? t.foreground : t.dim).cursor_pointer().hover((el) => el.bg(t.hover))
      .tooltip(this.showHidden ? "Fold the hidden tickets" : "Show the hidden tickets")
      .on_click((_e, cx) => { this.showHidden = !this.showHidden; cx.notify(); })
      .child(`+${hiddenTabs.length} hidden`);
    const tabRow = (tabs.length > 1 || hiddenTabs.length > 0) && h_flex().flex_none().flex_wrap().gap(4).px(8).pb(8)
      .children([...tabs.map(tab), ...(hiddenChip ? [hiddenChip] : []), ...(this.showHidden ? hiddenTabs.map(hiddenTab) : [])]);
    const option = Boolean(session) && h_flex().id("prs-branch-only").flex_none().mx(8).mb(6).px(8).h(28).gap(8).items_center().rounded(7)
      .text_size(11).text_color(t.muted).cursor_pointer().hover((el) => el.bg(t.hover))
      .tooltip("Also show the tickets this session has a branch for and no PR yet")
      .on_click((_e, cx) => {
        this.branchOnly = !this.branchOnly;
        localStorage.setItem("branchOnly", this.branchOnly ? "1" : "0");
        cx.notify();
      })
      .child(div().flex_none().w(13).h(13).rounded(4).border_1().border_color(this.branchOnly ? "#89b4fa" : t.dim)
        .child(div().id("prs-branch-only-on").size_full().rounded(3).bg("#89b4fa")
          .opacity(this.branchOnly ? 1 : 0).transition("opacity", { duration: 180, easing: "ease-out" })))
      .child(div().flex_1().min_w(0).truncate().child("Tickets without a PR"))
      .when(branchOnly > 0, (el) => el.child(div().flex_none().text_color(t.dim).child(String(branchOnly))));
    const autoOption = Boolean(session) && h_flex().id("prs-auto-hide").flex_none().mx(8).mb(6).px(8).h(28).gap(8).items_center().rounded(7)
      .text_size(11).text_color(t.muted).cursor_pointer().hover((el) => el.bg(t.hover))
      .tooltip("Hide a ticket once it is done in Jira and its PRs are merged")
      .on_click((_e, cx) => {
        this.autoHide = !this.autoHide;
        localStorage.setItem("autoHide", this.autoHide ? "1" : "0");
        this.sync();
        cx.notify();
      })
      .child(div().flex_none().w(13).h(13).rounded(4).border_1().border_color(this.autoHide ? "#89b4fa" : t.dim)
        .child(div().id("prs-auto-hide-on").size_full().rounded(3).bg("#89b4fa")
          .opacity(this.autoHide ? 1 : 0).transition("opacity", { duration: 180, easing: "ease-out" })))
      .child(div().flex_1().min_w(0).truncate().child("Hide finished tickets"));
    const head = h_flex().h(32).flex_none().px(12).items_center().gap(6).text_size(11.5).text_color(t.dim)
      .child(div().flex_none().font_semibold().text_color(t.muted).child("PRs"))
      .child(div().flex_1().min_w(0).truncate().text_color(t.muted).child(session ?? ""))
      .when(this.loading, (el) => el.child(svg("mods/workspace-chrome/spinner.svg").size(11).flex_none().spin(900)))
      .when(Boolean(session), (el) => el.child(this.copyButton(t, prs)))
      .when(!this.loading && Boolean(session), (el) => el.child(div().id("prs-refresh").flex_none().px(5).rounded(4).cursor_pointer()
        .text_size(13).hover((h) => h.bg(t.hover).text_color(t.foreground)).tooltip("Refresh PR status and CI from Stash")
        .on_click((_e, cx) => this.load(cx, true)).child("↻")));
    const row = (p) => {
      const c = CI[p.ci] ?? CI.none;
      return h_flex().id(`pr-${p.key}`).h(28).flex_none().px(8).gap(8).items_center().rounded(7)
        .cursor_pointer().hover((el) => el.bg(t.hover))
        .tooltip(`${p.title}\n${p.label}`)
        .on_click(() => open(p.url))
        .child(div().flex_none().w(36).text_size(11).text_color(t.dim).child(`#${p.number}`))
        .child(div().id(`ci-${p.key}`).flex_none().w(12).text_size(11).font_bold().text_color(c[1] ?? t.dim).tooltip(c[2])
          .when(Boolean(p.ci_url) && p.ci !== "none", (el) => el.cursor_pointer().on_mouse_down("left", (_e, cx) => cx.stop_propagation())
            .on_click((_e, cx) => { cx.stop_propagation(); open(p.ci_url); }))
          .child(c[0]))
        .child(div().flex_1().min_w(0).truncate().text_size(12.5).text_color(p.state === "OPEN" ? t.foreground : t.muted)
          .child(this.untitled(p.title ?? "")))
        .child(div().flex_none().px(5).h(16).rounded(4).flex().items_center().text_size(10).font_semibold()
          .bg(tone(t, p) + "26").text_color(tone(t, p)).child(shortLabel(p)));
    };
    const cat = ticket?.category === "Done" ? "#a6e3a1" : ticket?.category === "In Progress" ? "#f9e2af" : t.dim;
    const ticketCard = ticket && v_flex().id("ticket").mx(8).mb(4).px(10).py(7).gap(3).rounded(8).bg(t.surface ?? t.hover)
      .cursor_pointer().hover((el) => el.opacity(0.85)).tooltip(`Open ${ticket.key} in Jira`)
      .on_click(() => { const base = this.data.config?.jira_url; if (base) open(`${base}/browse/${ticket.key}`); })
      .child(h_flex().gap(6).items_center().text_size(11.5)
        .child(div().flex_none().font_semibold().text_color("#89b4fa").child(ticket.key))
        .child(div().flex_1())
        .when(Boolean(ticket.status), (el) => el.child(div().flex_none().px(5).h(16).rounded(4).flex().items_center().text_size(10).font_semibold()
          .bg(cat + "26").text_color(cat).child(ticket.status))))
      .when(Boolean(ticket.summary), (el) => el.child(div().text_size(12).text_color(t.muted).truncate().child(ticket.summary)));
    const body = !session
      ? [div().px(14).pt(6).text_size(12).text_color(t.dim).child("Focus a Claude session to see its PRs.")]
      : !prs.length
        ? [div().px(14).pt(6).text_size(12).text_color(t.dim).child(this.loading && !cur ? "Loading…" : cur ? "No PR yet." : "No PRs of yours in this session."),
          ...(cur?.branches ?? []).map((b) => div().px(14).pt(4).text_size(11.5).text_color(t.muted).truncate().child(b))]
        : [...repos].flatMap(([repo, list]) => [
          div().px(8).pt(10).pb(3).text_size(11).text_color(t.dim).truncate().child(repo),
          ...[...list].sort((a, b) => (a.state === "OPEN" ? 0 : 1) - (b.state === "OPEN" ? 0 : 1) || b.number - a.number).map(row),
        ]);
    const docRow = (d) => h_flex().id(`doc-${d.path}`).h(26).flex_none().px(8).gap(8).items_center().rounded(7)
      .cursor_pointer().hover((el) => el.bg(t.hover)).tooltip(`${d.folder}/${d.name}`)
      .on_click(() => open(d.path))
      .child(svg("mods/files/file.svg").size(12).flex_none().text_color(t.dim))
      .child(div().flex_1().min_w(0).truncate().text_size(12.5).text_color(t.foreground).child(d.name))
      .child(div().flex_none().max_w(110).truncate().text_size(10.5).text_color(t.dim).child(d.folder.split("/").pop()));
    const docs = session && this.docs.length ? [
      div().px(8).pt(16).pb(3).text_size(11).text_color(t.dim).child(`Docs · ${this.docs.length}`),
      ...this.docs.slice(0, 15).map(docRow),
    ] : [];
    return v_flex().size_full().min_h(0).bg(t.chrome).text_color(t.foreground).text_size(13)
      .child(head)
      .when(Boolean(tabRow), (el) => el.child(tabRow))
      .when(Boolean(option), (el) => el.child(option))
      .when(Boolean(autoOption), (el) => el.child(autoOption))
      .child(v_flex().id("prs-content").relative().flex_1().min_h(0)
        .top(this.entering ? 8 : 0).opacity(this.entering ? 0 : 1)
        .transition("top", { duration: this.entering ? 1 : 260, easing: "ease-out" })
        .transition("opacity", { duration: this.entering ? 1 : 260, easing: "ease-out" })
        .when(Boolean(ticketCard), (el) => el.child(ticketCard))
        .child(v_flex().flex_1().min_h(0).px(6).pb(14).overflow_y_scrollbar().children([...body, ...docs])));
  }
}
