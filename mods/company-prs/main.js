// The focused Claude session's own PRs, with their Stash review state and CI, its Jira ticket, and the markdown files it wrote.

import { View, div, svg } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import { focused, exec, appHome, theme, checking } from "herdr";

const JIRA = "https://jira.ovhcloud.tools";
const CI = {
  failed: ["✕", "#f38ba8", "CI failed · click to open the build"],
  inprogress: ["●", "#f9e2af", "CI running · click to open the build"],
  successful: ["✓", "#a6e3a1", "CI passed"],
  none: ["–", null, "No CI build on the last commit"],
};
const HELPER = () => `${appHome()}/mods/company-prs/sessions.py`;
const open = (url) => exec("open", [url]).catch(() => null);

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
    this.data = { session: null, ticket: null, prs: [] };
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
    const { session, ticket, prs } = this.data;
    const repos = new Map();
    for (const p of prs) { if (!repos.has(p.repo)) repos.set(p.repo, []); repos.get(p.repo).push(p); }
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
          .child((p.title ?? "").replace(/^PDATA-\d+[:\s]+/i, "")))
        .child(div().flex_none().px(5).h(16).rounded(4).flex().items_center().text_size(10).font_semibold()
          .bg(tone(t, p) + "26").text_color(tone(t, p)).child(shortLabel(p)));
    };
    const cat = ticket?.category === "Done" ? "#a6e3a1" : ticket?.category === "In Progress" ? "#f9e2af" : t.dim;
    const ticketCard = ticket && v_flex().id("ticket").mx(8).mb(4).px(10).py(7).gap(3).rounded(8).bg(t.surface ?? t.hover)
      .cursor_pointer().hover((el) => el.opacity(0.85)).tooltip(`Open ${ticket.key} in Jira`)
      .on_click(() => open(`${JIRA}/browse/${ticket.key}`))
      .child(h_flex().gap(6).items_center().text_size(11.5)
        .child(div().flex_none().font_semibold().text_color("#89b4fa").child(ticket.key))
        .child(div().flex_1())
        .when(Boolean(ticket.status), (el) => el.child(div().flex_none().px(5).h(16).rounded(4).flex().items_center().text_size(10).font_semibold()
          .bg(cat + "26").text_color(cat).child(ticket.status))))
      .when(Boolean(ticket.summary), (el) => el.child(div().text_size(12).text_color(t.muted).truncate().child(ticket.summary)));
    const body = !session
      ? [div().px(14).pt(6).text_size(12).text_color(t.dim).child("Focus a Claude session to see its PRs.")]
      : !prs.length
        ? [div().px(14).pt(6).text_size(12).text_color(t.dim).child(this.loading ? "Loading…" : "No PRs of yours in this session.")]
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
      .when(Boolean(ticketCard), (el) => el.child(ticketCard))
      .child(v_flex().flex_1().min_h(0).px(6).pb(14).overflow_y_scrollbar().children([...body, ...docs]));
  }
}
