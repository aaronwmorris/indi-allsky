class le {
  /**
   * @type {T}
   */
  #t;
  #e = /* @__PURE__ */ new Set();
  /**
   * @param {T} current
   */
  constructor(t) {
    this.#t = t;
  }
  /**
   * @return {T}
   */
  get current() {
    return this.#t;
  }
  /**
   * @param {T} value
   */
  set current(t) {
    this.#t != t && (this.#t = t, this.#e.forEach((n) => n(t)));
  }
  /**
   * @type {import("hooks").Ref["on"]}
   */
  on(t) {
    return this.#e.add(t), () => this.#e.delete(t);
  }
}
const Rt = (e) => new le(e), st = Symbol.for("atomico.hooks");
globalThis[st] = globalThis[st] || {};
let A = globalThis[st];
const ue = Symbol.for("Atomico.suspense"), Yt = Symbol.for("Atomico.effect"), fe = Symbol.for("Atomico.layoutEffect"), Ft = Symbol.for("Atomico.insertionEffect"), R = (e, t, n) => {
  const { i: s, hooks: o } = A.c, r = o[s] = o[s] || {};
  return r.value = e(r.value), r.effect = t, r.tag = n, A.c.i++, o[s].value;
}, It = (e) => R((t = Rt(e)) => t), W = () => R((e = Rt(A.c.host)) => e), Lt = () => A.c.update, de = (e, t, n = 0) => {
  let s = {}, o = !1;
  const r = () => o, a = (l, c) => {
    for (const d in s) {
      const i = s[d];
      i.effect && i.tag === l && (i.value = i.effect(i.value, c));
    }
  };
  return { load: (l) => {
    A.c = { host: t, hooks: s, update: e, i: 0, id: n };
    let c;
    try {
      o = !1, c = l();
    } catch (d) {
      if (d !== ue) throw d;
      o = !0;
    } finally {
      A.c = null;
    }
    return c;
  }, cleanEffects: (l) => (a(Ft, l), () => (a(fe, l), () => {
    a(Yt, l);
  })), isSuspense: r };
}, x = Symbol.for;
function xt(e, t) {
  const n = e.length;
  if (n !== t.length) return !1;
  for (let s = 0; s < n; s++) {
    let o = e[s], r = t[s];
    if (o !== r) return !1;
  }
  return !0;
}
const M = (e) => typeof e == "function", F = (e) => typeof e == "object", { isArray: he } = Array, ot = (e, t) => (t ? e instanceof HTMLStyleElement : !0) && "hydrate" in (e?.dataset || {});
function _t(e, t) {
  let n;
  const s = (o) => {
    let { length: r } = o;
    for (let a = 0; a < r; a++) {
      const u = o[a];
      if (u && Array.isArray(u))
        s(u);
      else {
        const f = typeof u;
        if (u == null || f === "function" || f === "boolean")
          continue;
        f === "string" || f === "number" ? (n == null && (n = ""), n += u) : (n != null && (t(n), n = null), t(u));
      }
    }
  };
  s(e), n != null && t(n);
}
const jt = (e, t, n) => (e.addEventListener(t, n), () => e.removeEventListener(t, n));
class Bt {
  /**
   *
   * @param {HTMLElement} target
   * @param {string} message
   * @param {string} value
   */
  constructor(t, n, s) {
    this.message = n, this.target = t, this.value = s;
  }
}
class qt extends Bt {
}
class me extends Bt {
}
const z = "Custom", ye = null, pe = { true: 1, "": 1, 1: 1 };
function ge(e, t, n, s, o) {
  const {
    type: r,
    reflect: a,
    event: u,
    value: f,
    attr: l = be(t)
  } = n?.name != z && F(n) && n != ye ? n : { type: n }, c = r?.name === z && r.map, d = f != null ? r == Function || !M(f) ? () => f : f : null;
  Object.defineProperty(e, t, {
    configurable: !0,
    /**
     * @this {import("dom").AtomicoThisInternal}
     * @param {any} newValue
     */
    set(i) {
      const m = this[t];
      d && r != Boolean && i == null && (i = d());
      const { error: g, value: b } = (c ? Te : Ee)(
        r,
        i
      );
      if (g && b != null)
        throw new qt(
          this,
          `The value defined for prop '${t}' must be of type '${r.name}'`,
          b
        );
      m != b && (this._props[t] = b ?? void 0, this.update(), u && zt(this, u), this.updated.then(() => {
        a && (this._ignoreAttr = l, De(this, r, l, this[t]), this._ignoreAttr = null);
      }));
    },
    /**
     * @this {import("dom").AtomicoThisInternal}
     */
    get() {
      return this._props[t];
    }
  }), d && (o[t] = d()), s[l] = { prop: t, type: r };
}
const zt = (e, { type: t, base: n = CustomEvent, ...s }) => e.dispatchEvent(new n(t, s)), be = (e) => e.replace(/([A-Z])/g, "-$1").toLowerCase(), De = (e, t, n, s) => s == null || t == Boolean && !s ? e.removeAttribute(n) : e.setAttribute(
  n,
  t?.name === z && t?.serialize ? t?.serialize(s) : F(s) ? JSON.stringify(s) : t == Boolean ? "" : s
), Ce = (e, t) => e == Boolean ? !!pe[t] : e == Number ? Number(t) : e == String ? t : e == Array || e == Object ? JSON.parse(t) : e.name == z ? t : (
  // TODO: If when defining reflect the prop can also be of type string?
  new e(t)
), Te = ({ map: e }, t) => {
  try {
    return { value: e(t), error: !1 };
  } catch {
    return { value: t, error: !0 };
  }
}, Ee = (e, t) => e == null || t == null ? { value: t, error: !1 } : e != String && t === "" ? { value: void 0, error: !1 } : e == Object || e == Array || e == Symbol ? {
  value: t,
  error: {}.toString.call(t) !== `[object ${e.name}]`
} : t instanceof e ? {
  value: t,
  error: e == Number && Number.isNaN(t.valueOf())
} : e == String || e == Number || e == Boolean ? {
  value: t,
  error: e == Number ? typeof t != "number" ? !0 : Number.isNaN(t) : e == String ? typeof t != "string" : typeof t != "boolean"
} : { value: t, error: !0 };
let ve = 0;
const we = (e) => {
  const t = (e?.dataset || {})?.hydrate || "";
  return t || "c" + ve++;
}, k = (e, t = HTMLElement) => {
  const n = {}, s = {}, o = "prototype" in t && t.prototype instanceof Element, r = o ? t : "base" in t ? t.base : HTMLElement, { props: a, styles: u } = o ? e : t;
  class f extends r {
    constructor() {
      super(), this._setup(), this._render = () => e({ ...this._props });
      for (const c in s) this[c] = s[c];
    }
    /**
     * @returns {import("core").Sheets[]}
     */
    static get styles() {
      return [super.styles, u];
    }
    async _setup() {
      if (this._props) return;
      this._props = {};
      let c, d;
      this.mounted = new Promise(
        (y) => this.mount = () => {
          y(), c != this.parentNode && (d != c ? this.unmounted.then(this.update) : this.update()), c = this.parentNode;
        }
      ), this.unmounted = new Promise(
        (y) => this.unmount = () => {
          y(), (c != this.parentNode || !this.isConnected) && (i.cleanEffects(!0)()(), d = this.parentNode, c = null);
        }
      ), this.symbolId = this.symbolId || Symbol(), this.symbolIdParent = Symbol();
      const i = de(
        () => this.update(),
        this,
        we(this)
      );
      let m, g = !0;
      const b = ot(this);
      this.update = () => (m || (m = !0, this.updated = (this.updated || this.mounted).then(() => {
        try {
          const y = i.load(this._render), p = i.cleanEffects();
          return y && //@ts-ignore
          y.render(this, this.symbolId, b), m = !1, g && !i.isSuspense() && (g = !1, !b && Se(this)), p();
        } finally {
          m = !1;
        }
      }).then(
        /**
         * @param {import("internal/hooks.js").CleanUseEffects} [cleanUseEffect]
         */
        (y) => {
          y && y();
        }
      )), this.updated), this.update();
    }
    connectedCallback() {
      this.mount(), super.connectedCallback && super.connectedCallback();
    }
    disconnectedCallback() {
      super.disconnectedCallback && super.disconnectedCallback(), this.unmount();
    }
    /**
     * @this {import("dom").AtomicoThisInternal}
     * @param {string} attr
     * @param {(string|null)} oldValue
     * @param {(string|null)} value
     */
    attributeChangedCallback(c, d, i) {
      if (n[c]) {
        if (c === this._ignoreAttr || d === i) return;
        const { prop: m, type: g } = n[c];
        try {
          this[m] = Ce(g, i);
        } catch {
          throw new me(
            this,
            `The value defined as attr '${c}' cannot be parsed by type '${g.name}'`,
            i
          );
        }
      } else
        super.attributeChangedCallback(c, d, i);
    }
    static get props() {
      return { ...super.props, ...a };
    }
    static get observedAttributes() {
      const c = super.observedAttributes || [];
      for (const d in a)
        ge(this.prototype, d, a[d], n, s);
      return Object.keys(n).concat(c);
    }
  }
  return f;
};
function Se(e) {
  const { styles: t } = e.constructor, { shadowRoot: n } = e;
  if (n && t.length) {
    const s = [];
    _t(t, (o) => {
      o && (o instanceof Element ? n.appendChild(o.cloneNode(!0)) : s.push(o));
    }), s.length && (n.adoptedStyleSheets = s);
  }
}
const Ht = (e) => (t, n) => {
  R(
    /**
     * Clean the effect hook
     * @type {import("internal/hooks.js").CollectorEffect}
     */
    ([s, o] = []) => ((o || !o) && (o && xt(o, n) ? s = s || !0 : (M(s) && s(), s = null)), [s, n]),
    /**
     * @returns {any}
     */
    ([s, o], r) => r ? (M(s) && s(), []) : [s || t(), o],
    e
  );
}, L = Ht(Yt), Me = Ht(Ft);
class Wt extends Array {
  /**
   *
   * @param {any} initialState
   * @param {(nextState: any, state:any[], mount: boolean )=>void} mapState
   */
  constructor(t, n) {
    let s = !0;
    const o = (r) => {
      try {
        n(r, this, s);
      } finally {
        s = !1;
      }
    };
    super(void 0, o, n), o(t);
  }
  /**
   * The following code allows a mutable approach to useState
   * and useProp this with the idea of allowing an alternative
   * approach similar to Vue or Qwik of state management
   * @todo pending review with the community
   */
  // get value() {
  //     return this[0];
  // }
  // set value(nextState) {
  //     this[2](nextState, this);
  // }
}
const it = (e) => {
  const t = Lt();
  return R(
    (n = new Wt(e, (s, o, r) => {
      s = M(s) ? s(o[0]) : s, s !== o[0] && (o[0] = s, r || t());
    })) => n
  );
}, w = (e, t) => {
  const [n] = R(([s, o, r = 0] = []) => ((!o || o && !xt(o, t)) && (s = e()), [s, t, r]));
  return n;
}, lt = (e) => {
  const { current: t } = W();
  if (!(e in t))
    throw new qt(
      t,
      `For useProp("${e}"), the prop does not exist on the host.`,
      e
    );
  return R(
    (n = new Wt(t[e], (s, o) => {
      s = M(s) ? s(t[e]) : s, t[e] = s;
    })) => (n[0] = t[e], n)
  );
}, N = (e, t = {}) => {
  const n = W();
  return n[e] || (n[e] = (s = t.detail) => zt(n.current, {
    type: e,
    ...t,
    detail: s
  })), n[e];
}, rt = x("atomico/options");
globalThis[rt] = globalThis[rt] || {
  sheet: !!document.adoptedStyleSheets
};
const K = globalThis[rt], Ne = new Promise((e) => {
  K.ssr || (document.readyState === "loading" ? jt(document, "DOMContentLoaded", e) : e());
}), Pe = {
  checked: 1,
  value: 1,
  selected: 1
}, ke = {
  list: 1,
  type: 1,
  size: 1,
  form: 1,
  width: 1,
  height: 1,
  src: 1,
  href: 1,
  slot: 1
}, Oe = {
  shadowDom: 1,
  staticNode: 1,
  cloneNode: 1,
  children: 1,
  key: 1
}, q = {}, at = [];
class ct extends Text {
}
const Ae = x("atomico/id"), I = x("atomico/type"), Q = x("atomico/ref"), Kt = x("atomico/vnode"), Jt = () => {
};
function Ue(e, t, n) {
  return Xt(this, e, t, n);
}
const Zt = (e, t, ...n) => {
  const s = t || q;
  let { children: o } = s;
  if (o = o ?? (n.length ? n : at), e === Jt)
    return o;
  const r = e ? e instanceof Node ? 1 : (
    //@ts-ignore
    e.prototype instanceof HTMLElement && 2
  ) : 0;
  if (r === !1 && e instanceof Function)
    return e(
      o != at ? { children: o, ...s } : s
    );
  const a = K.render || Ue;
  return {
    [I]: Kt,
    type: e,
    props: s,
    children: o,
    key: s.key,
    // key for lists by keys
    // define if the node declares its shadowDom
    shadow: s.shadowDom,
    // allows renderings to run only once
    static: s.staticNode,
    // defines whether the type is a childNode `1` or a constructor `2`
    raw: r,
    // defines whether to use the second parameter for document.createElement
    is: s.is,
    // clone the node if it comes from a reference
    clone: s.cloneNode,
    render: a
  };
};
function Xt(e, t, n = Ae, s, o) {
  let r;
  if (t && t[n] && t[n].vnode == e || e[I] != Kt)
    return t;
  (e || !t) && (o = o || e.type == "svg", r = e.type != "host" && (e.raw == 1 ? (t && e.clone ? t[Q] : t) != e.type : e.raw == 2 ? !(t instanceof e.type) : t ? t[Q] || t.localName != e.type : !t), r && e.type != null && (e.raw == 1 && e.clone ? (s = !0, t = e.type.cloneNode(!0), t[Q] = e.type) : t = e.raw == 1 ? e.type : e.raw == 2 ? new e.type() : o ? document.createElementNS(
    "http://www.w3.org/2000/svg",
    e.type
  ) : document.createElement(
    e.type,
    e.is ? { is: e.is } : void 0
  )));
  const a = t[n] ? t[n] : q, { vnode: u = q, cycle: f = 0 } = a;
  let { fragment: l, handlers: c } = a;
  const { children: d = at, props: i = q } = u;
  if (c = r ? {} : c || {}, e.static && !r) return t;
  if (e.shadow && !t.shadowRoot && // @ts-ignore
  t.attachShadow({ mode: "open", ...e.shadow }), e.props != i && Ye(t, i, e.props, c, o), e.children !== d) {
    const m = e.shadow ? t.shadowRoot : t;
    l = Re(
      e.children,
      /**
       * @todo for hydration use attribute and send childNodes
       */
      l,
      m,
      n,
      // add support to foreignObject, children will escape from svg
      !f && s,
      o && e.type == "foreignObject" ? !1 : o
    );
  }
  return t[n] = { vnode: e, handlers: c, fragment: l, cycle: f + 1 }, t;
}
function $e(e, t) {
  const n = new ct(""), s = new ct("");
  let o;
  if (e[t ? "prepend" : "append"](n), t) {
    let { lastElementChild: r } = e;
    for (; r; ) {
      const { previousElementSibling: a } = r;
      if (ot(r, !0) && !ot(a, !0)) {
        o = r;
        break;
      }
      r = a;
    }
  }
  return o ? o.before(s) : e.append(s), {
    markStart: n,
    markEnd: s
  };
}
function Re(e, t, n, s, o, r) {
  e = e == null ? null : he(e) ? e : [e];
  const a = t || $e(n, o), { markStart: u, markEnd: f, keyes: l } = a;
  let c;
  const d = l && /* @__PURE__ */ new Set();
  let i = u;
  if (e && _t(e, (m) => {
    if (typeof m == "object" && !m[I])
      return;
    const g = m[I] && m.key, b = l && g != null && l.get(g);
    i != f && i === b ? d.delete(i) : i = i == f ? f : i.nextSibling;
    const y = l ? b : i;
    let p = y;
    if (m[I])
      p = Xt(m, y, s, o, r);
    else {
      const v = m + "";
      !(p instanceof Text) || p instanceof ct ? p = new Text(v) : p.data != v && (p.data = v);
    }
    p != i && (l && d.delete(p), !y || l ? (n.insertBefore(p, i), l && i != f && d.add(i)) : y == f ? n.insertBefore(p, f) : (n.replaceChild(p, y), i = p)), g != null && (c = c || /* @__PURE__ */ new Map(), c.set(g, p));
  }), i = i == f ? f : i.nextSibling, t && i != f)
    for (; i != f; ) {
      const m = i;
      i = i.nextSibling, m.remove();
    }
  return d && d.forEach((m) => m.remove()), a.keyes = c, a;
}
function Ye(e, t, n, s, o) {
  for (const r in t)
    !(r in n) && St(e, r, t[r], null, o, s);
  for (const r in n)
    St(e, r, t[r], n[r], o, s);
}
function St(e, t, n, s, o, r) {
  if (t = t == "class" && !o ? "className" : t, n = n ?? null, s = s ?? null, t in e && Pe[t] && (n = e[t]), !(s === n || Oe[t] || t[0] == "_"))
    if (e.localName === "slot" && t === "assignNode" && "assign" in e)
      e.assign(s);
    else if (t[0] == "o" && t[1] == "n" && (M(s) || M(n)))
      Fe(e, t.slice(2), s, r);
    else if (t == "ref")
      s && (M(s) ? s(e) : s.current = e);
    else if (t == "style") {
      const { style: a } = e;
      n = n || "", s = s || "";
      const u = F(n), f = F(s);
      if (u)
        for (const l in n)
          if (f)
            !(l in s) && Mt(a, l, null);
          else
            break;
      if (f)
        for (const l in s) {
          const c = s[l];
          u && n[l] === c || Mt(a, l, c);
        }
      else
        a.cssText = s;
    } else {
      const a = t[0] == "$" ? t.slice(1) : t;
      a === t && (!o && !ke[t] && t in e || M(s) || M(n)) ? e[t] = s ?? "" : s == null ? e.removeAttribute(a) : e.setAttribute(
        a,
        F(s) ? JSON.stringify(s) : s
      );
    }
}
function Fe(e, t, n, s) {
  if (s.handleEvent || (s.handleEvent = (o) => s[o.type].call(e, o)), n) {
    if (!s[t]) {
      const o = n.capture || n.once || n.passive ? Object.assign({}, n) : null;
      e.addEventListener(t, s, o);
    }
    s[t] = n;
  } else
    s[t] && (e.removeEventListener(t, s), delete s[t]);
}
function Mt(e, t, n) {
  let s = "setProperty";
  n == null && (s = "removeProperty", n = null), ~t.indexOf("-") ? e[s](t, n) : e[t] = n;
}
const Ie = Zt("host", { style: "display: contents" }), Gt = "value", Le = (e, t) => {
  const n = W(), s = It();
  Me(
    () => jt(
      n.current,
      "ConnectContext",
      /**
       * @param {CustomEvent<import("context").DetailConnectContext>} event
       */
      (o) => {
        o.composedPath().at(0) !== o.currentTarget && e === o.detail.id && (o.stopPropagation(), o.detail.connect(s));
      }
    ),
    [e]
  ), s.current = t;
}, ut = (e) => {
  const t = N("ConnectContext", {
    bubbles: !0,
    composed: !0
  }), [n, s] = it(() => {
    if (K.ssr) return;
    let r;
    return t({
      id: e,
      /**
       * @param {import("core").Ref} parentContext
       */
      connect(a) {
        r = a;
      }
    }), r;
  }), o = Lt();
  return L(() => {
    Ne.then(
      () => t({
        id: e,
        connect: s
      })
    );
  }, [e]), L(() => {
    if (n)
      return n.on(o);
  }, [n]), n?.current || e[Gt];
}, Qt = (e) => {
  const t = k(
    ({ value: n }) => (Le(t, n), Ie),
    {
      props: {
        value: {
          type: Object,
          value: () => e
        }
      }
    }
  );
  return t[Gt] = e, t;
};
Qt({
  /**
   *
   * @param {string} type
   * @param {string} id
   */
  dispatch(e, t) {
  }
});
const Nt = {};
function J(e, ...t) {
  const n = (e.raw || e).reduce(
    (s, o, r) => s + o + (t[r] || ""),
    ""
  );
  return Nt[n] = Nt[n] || xe(n);
}
function xe(e) {
  if (K.sheet) {
    const t = new CSSStyleSheet();
    return t.replaceSync(e), t;
  } else {
    const t = document.createElement("style");
    return t.textContent = e, t;
  }
}
const h = (e, t, n) => (t == null ? t = { key: n } : t.key = n, Zt(e, t)), S = h, ft = J`*,*:before,*:after{box-sizing:border-box}button{padding:0;touch-action:manipulation;cursor:pointer;user-select:none}`, dt = J`.vh{position:absolute;transform:scale(0)}`;
function ht() {
  const e = /* @__PURE__ */ new Date();
  return new C(e.getFullYear(), e.getMonth() + 1, e.getDate());
}
const _e = 864e5;
function je(e) {
  const t = E(e);
  t.setUTCDate(t.getUTCDate() + 3 - (t.getUTCDay() + 6) % 7);
  const n = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
  return 1 + Math.round(
    ((t.getTime() - n.getTime()) / _e - 3 + (n.getUTCDay() + 6) % 7) / 7
  );
}
function mt(e, t = 0) {
  const n = E(e), s = n.getUTCDay(), o = (s < t ? 7 : 0) + s - t;
  return n.setUTCDate(n.getUTCDate() - o), C.from(n);
}
function Vt(e, t = 0) {
  return mt(e, t).add({ days: 6 });
}
function te(e) {
  return C.from(new Date(Date.UTC(e.year, e.month, 0)));
}
function Z(e, t, n) {
  return t && C.compare(e, t) < 0 ? t : n && C.compare(e, n) > 0 ? n : e;
}
const Be = { days: 1 };
function qe(e, t = 0) {
  let n = mt(e.toPlainDate(), t);
  const s = Vt(te(e), t), o = [];
  for (; C.compare(n, s) < 0; ) {
    const r = [];
    for (let a = 0; a < 7; a++)
      r.push(n), n = n.add(Be);
    o.push(r);
  }
  return o;
}
function E(e) {
  return new Date(Date.UTC(e.year, e.month - 1, e.day ?? 1));
}
const ze = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[0-1])$/, V = (e, t) => e.toString().padStart(t, "0");
class C {
  constructor(t, n, s) {
    this.year = t, this.month = n, this.day = s;
  }
  // this is an incomplete implementation that only handles arithmetic on a single unit at a time.
  // i didn't want to get into more complex arithmetic since it get tricky fast
  // this is enough to serve my needs and will still be a drop-in replacement when actual Temporal API lands
  add(t) {
    const n = E(this);
    if ("days" in t)
      return n.setUTCDate(this.day + t.days), C.from(n);
    let { year: s, month: o } = this;
    "months" in t ? (o = this.month + t.months, n.setUTCMonth(o - 1)) : (s = this.year + t.years, n.setUTCFullYear(s));
    const r = C.from(E({ year: s, month: o, day: 1 }));
    return Z(C.from(n), r, te(r));
  }
  toString() {
    return `${V(this.year, 4)}-${V(this.month, 2)}-${V(this.day, 2)}`;
  }
  toPlainYearMonth() {
    return new U(this.year, this.month);
  }
  equals(t) {
    return C.compare(this, t) === 0;
  }
  static compare(t, n) {
    return t.year < n.year ? -1 : t.year > n.year ? 1 : t.month < n.month ? -1 : t.month > n.month ? 1 : t.day < n.day ? -1 : t.day > n.day ? 1 : 0;
  }
  static from(t) {
    if (typeof t == "string") {
      const n = t.match(ze);
      if (!n)
        throw new TypeError(t);
      const [, s, o, r] = n;
      return new C(
        parseInt(s, 10),
        parseInt(o, 10),
        parseInt(r, 10)
      );
    }
    return new C(
      t.getUTCFullYear(),
      t.getUTCMonth() + 1,
      t.getUTCDate()
    );
  }
}
class U {
  constructor(t, n) {
    this.year = t, this.month = n;
  }
  add(t) {
    const n = E(this), s = (t.months ?? 0) + (t.years ?? 0) * 12;
    return n.setUTCMonth(n.getUTCMonth() + s), new U(n.getUTCFullYear(), n.getUTCMonth() + 1);
  }
  equals(t) {
    return this.year === t.year && this.month === t.month;
  }
  toPlainDate() {
    return new C(this.year, this.month, 1);
  }
  static compare(t, n) {
    return t.year < n.year ? -1 : t.year > n.year ? 1 : t.month < n.month ? -1 : t.month > n.month ? 1 : 0;
  }
}
function H(e, t) {
  if (t)
    try {
      return e.from(t);
    } catch {
    }
}
function P(e) {
  const [t, n] = lt(e);
  return [w(() => H(C, t), [t]), (r) => n(r?.toString())];
}
function He(e) {
  const [t = "", n] = lt(e);
  return [w(() => {
    const [r, a] = t.split("/"), u = H(C, r), f = H(C, a);
    return u && f ? [u, f] : [];
  }, [t]), (r) => n(`${r[0]}/${r[1]}`)];
}
function We(e) {
  const [t = "", n] = lt(e);
  return [w(() => {
    const r = [];
    for (const a of t.trim().split(/\s+/)) {
      const u = H(C, a);
      u && r.push(u);
    }
    return r;
  }, [t]), (r) => n(r.join(" "))];
}
function $(e, t) {
  return w(
    () => new Intl.DateTimeFormat(t, { timeZone: "UTC", ...e }),
    [t, e]
  );
}
function Pt(e, t, n) {
  const s = $(e, n);
  return w(() => {
    const o = [], r = /* @__PURE__ */ new Date();
    for (var a = 0; a < 7; a++) {
      const u = (r.getUTCDay() - t + 7) % 7;
      o[u] = s.format(r), r.setUTCDate(r.getUTCDate() + 1);
    }
    return o;
  }, [t, s]);
}
const kt = (e, t, n) => Z(e, t, n) === e, Ot = (e) => e.target.matches(":dir(ltr)"), Ke = { month: "long", day: "numeric" }, Je = { month: "long" }, Ze = { weekday: "long" }, tt = { bubbles: !0 };
function Xe({ props: e, context: t }) {
  const { offset: n } = e, {
    firstDayOfWeek: s,
    isDateDisallowed: o,
    min: r,
    max: a,
    today: u,
    page: f,
    locale: l,
    focusedDate: c,
    formatWeekday: d
  } = t, i = u ?? ht(), m = Pt(Ze, s, l), g = w(
    () => ({ weekday: d }),
    [d]
  ), b = Pt(g, s, l), y = $(Ke, l), p = $(Je, l), v = w(
    () => f.start.add({ months: n }),
    [f, n]
  ), X = w(
    () => qe(v, s),
    [v, s]
  ), se = N("focusday", tt), oe = N("selectday", tt), re = N("hoverday", tt);
  function Dt(D) {
    se(Z(D, r, a));
  }
  function ae(D) {
    let T;
    switch (D.key) {
      case "ArrowRight":
        T = c.add({ days: Ot(D) ? 1 : -1 });
        break;
      case "ArrowLeft":
        T = c.add({ days: Ot(D) ? -1 : 1 });
        break;
      case "ArrowDown":
        T = c.add({ days: 7 });
        break;
      case "ArrowUp":
        T = c.add({ days: -7 });
        break;
      case "PageUp":
        T = c.add(D.shiftKey ? { years: -1 } : { months: -1 });
        break;
      case "PageDown":
        T = c.add(D.shiftKey ? { years: 1 } : { months: 1 });
        break;
      case "Home":
        T = mt(c, s);
        break;
      case "End":
        T = Vt(c, s);
        break;
      default:
        return;
    }
    Dt(T), D.preventDefault();
  }
  function ce(D) {
    const T = v.equals(D);
    if (!t.showOutsideDays && !T)
      return;
    const ie = D.equals(c), Ct = D.equals(i), j = E(D), B = o?.(j), Tt = !kt(D, r, a);
    let Et = "", O;
    if (t.type === "range") {
      const [Y, G] = t.value, vt = Y?.equals(D), wt = G?.equals(D);
      O = Y && G && kt(D, Y, G), Et = `${vt ? "range-start" : ""} ${wt ? "range-end" : ""} ${O && !vt && !wt ? "range-inner" : ""}`;
    } else t.type === "multi" ? O = t.value.some((Y) => Y.equals(D)) : O = t.value?.equals(D);
    return {
      part: `${`button day day-${j.getUTCDay()} ${// we don't want outside days to ever be shown as selected
      T ? O ? "selected" : "" : "outside"} ${B ? "disallowed" : ""} ${Ct ? "today" : ""} ${t.getDayParts?.(j) ?? ""}`} ${Et}`,
      tabindex: T && ie ? 0 : -1,
      disabled: Tt,
      "aria-disabled": B ? "true" : void 0,
      "aria-pressed": T && O,
      "aria-current": Ct ? "date" : void 0,
      "aria-label": y.format(j),
      onkeydown: ae,
      onclick() {
        B || oe(D), Dt(D);
      },
      onmouseover() {
        !B && !Tt && re(D);
      }
    };
  }
  return {
    weeks: X,
    yearMonth: v,
    daysLong: m,
    daysVisible: b,
    formatter: p,
    getDayProps: ce
  };
}
const et = ht(), _ = Qt({
  type: "date",
  firstDayOfWeek: 1,
  focusedDate: et,
  page: { start: et.toPlainYearMonth(), end: et.toPlainYearMonth() }
});
customElements.define("calendar-ctx", _);
const Ge = (e, t) => (t + e) % 7, Qe = k(
  (e) => {
    const t = ut(_), n = It(), s = Xe({ props: e, context: t });
    function o() {
      n.current.querySelector("button[tabindex='0']")?.focus();
    }
    return /* @__PURE__ */ S("host", { shadowDom: !0, focus: o, children: [
      /* @__PURE__ */ h("div", { id: "h", part: "heading", children: s.formatter.format(E(s.yearMonth)) }),
      /* @__PURE__ */ S("table", { ref: n, "aria-labelledby": "h", part: "table", children: [
        /* @__PURE__ */ S("colgroup", { children: [
          t.showWeekNumbers && /* @__PURE__ */ h("col", { part: "col-weeknumber" }),
          /* @__PURE__ */ h("col", { part: "col-1" }),
          /* @__PURE__ */ h("col", { part: "col-2" }),
          /* @__PURE__ */ h("col", { part: "col-3" }),
          /* @__PURE__ */ h("col", { part: "col-4" }),
          /* @__PURE__ */ h("col", { part: "col-5" }),
          /* @__PURE__ */ h("col", { part: "col-6" }),
          /* @__PURE__ */ h("col", { part: "col-7" })
        ] }),
        /* @__PURE__ */ h("thead", { children: /* @__PURE__ */ S("tr", { part: "tr head", children: [
          t.showWeekNumbers && /* @__PURE__ */ h("th", { part: "th weeknumber", children: /* @__PURE__ */ S("slot", { name: "weeknumber", children: [
            /* @__PURE__ */ h("span", { class: "vh", children: "Week" }),
            /* @__PURE__ */ h("span", { "aria-hidden": "true", children: "#" })
          ] }) }),
          s.daysLong.map((r, a) => /* @__PURE__ */ S(
            "th",
            {
              part: `th day day-${Ge(t.firstDayOfWeek, a)}`,
              scope: "col",
              children: [
                /* @__PURE__ */ h("span", { class: "vh", children: r }),
                /* @__PURE__ */ h("span", { "aria-hidden": "true", children: s.daysVisible[a] })
              ]
            }
          ))
        ] }) }),
        /* @__PURE__ */ h("tbody", { children: s.weeks.map((r, a) => /* @__PURE__ */ S("tr", { part: "tr week", children: [
          t.showWeekNumbers && /* @__PURE__ */ h("th", { class: "num", part: "th weeknumber", scope: "row", children: je(r[0]) }),
          r.map((u, f) => {
            const l = s.getDayProps(u);
            return /* @__PURE__ */ h("td", { part: "td", children: l && /* @__PURE__ */ h("button", { class: "num", ...l, children: u.day }) }, f);
          })
        ] }, a)) })
      ] })
    ] });
  },
  {
    props: {
      offset: {
        type: Number,
        value: 0
      }
    },
    styles: [
      ft,
      dt,
      J`:host{--color-accent: black;--color-text-on-accent: white;display:flex;flex-direction:column;gap:.25rem;text-align:center;inline-size:fit-content}table{border-collapse:collapse;font-size:.875rem}th{inline-size:2.25rem;block-size:2.25rem}td{padding-inline:0}.num{font-variant-numeric:tabular-nums}button{color:inherit;font-size:inherit;background:transparent;border:0;block-size:2.25rem;inline-size:2.25rem}button:hover:where(:not(:disabled,[aria-disabled])){background:#0000000d}button:is([aria-pressed=true],:focus-visible){background:var(--color-accent);color:var(--color-text-on-accent)}button:focus-visible{outline:1px solid var(--color-text-on-accent);outline-offset:-2px}button:disabled,:host::part(outside),:host::part(disallowed){cursor:default;opacity:.5}`
    ]
  }
);
customElements.define("calendar-month", Qe);
function At(e) {
  return /* @__PURE__ */ h(
    "button",
    {
      part: `button ${e.name} ${e.onclick ? "" : "disabled"}`,
      onclick: e.onclick,
      "aria-disabled": e.onclick ? null : "true",
      children: /* @__PURE__ */ h("slot", { name: e.name, children: e.children })
    }
  );
}
function yt(e) {
  const t = E(e.page.start), n = E(e.page.end);
  return /* @__PURE__ */ h(
    _,
    {
      value: e,
      onselectday: e.onSelect,
      onfocusday: e.onFocus,
      onhoverday: e.onHover,
      children: /* @__PURE__ */ S("div", { role: "group", "aria-labelledby": "h", part: "container", children: [
        /* @__PURE__ */ h("div", { id: "h", class: "vh", "aria-live": "polite", "aria-atomic": "true", children: e.formatVerbose.formatRange(t, n) }),
        /* @__PURE__ */ S("div", { part: "header", children: [
          /* @__PURE__ */ h(At, { name: "previous", onclick: e.previous, children: "Previous" }),
          /* @__PURE__ */ h("slot", { part: "heading", name: "heading", children: /* @__PURE__ */ h("div", { "aria-hidden": "true", children: e.format.formatRange(t, n) }) }),
          /* @__PURE__ */ h(At, { name: "next", onclick: e.next, children: "Next" })
        ] }),
        /* @__PURE__ */ h("slot", { part: "months" })
      ] })
    }
  );
}
const pt = {
  value: {
    type: String,
    value: ""
  },
  min: {
    type: String,
    value: ""
  },
  max: {
    type: String,
    value: ""
  },
  today: {
    type: String,
    value: ""
  },
  isDateDisallowed: {
    type: Function,
    value: (e) => !1
  },
  formatWeekday: {
    type: String,
    value: () => "narrow"
  },
  getDayParts: {
    type: Function,
    value: (e) => ""
  },
  firstDayOfWeek: {
    type: Number,
    value: () => 1
  },
  showOutsideDays: {
    type: Boolean,
    value: !1
  },
  locale: {
    type: String,
    value: () => {
    }
  },
  months: {
    type: Number,
    value: 1
  },
  focusedDate: {
    type: String,
    value: () => {
    }
  },
  pageBy: {
    type: String,
    value: () => "months"
  },
  showWeekNumbers: {
    type: Boolean,
    value: !1
  }
}, gt = [
  ft,
  dt,
  J`:host{display:block;inline-size:fit-content}:host::part(container){display:flex;flex-direction:column;gap:1em}:host::part(header){display:flex;align-items:center;justify-content:space-between}:host::part(heading){font-weight:700;font-size:1.25em}:host::part(button){display:flex;align-items:center;justify-content:center}:host::part(button disabled){cursor:default;opacity:.5}`
], Ve = { year: "numeric" }, tn = { year: "numeric", month: "long" };
function nt(e, t) {
  return (t.year - e.year) * 12 + t.month - e.month;
}
const Ut = (e, t) => (e = t === 12 ? new U(e.year, 1) : e, {
  start: e,
  end: e.add({ months: t - 1 })
});
function en({
  pageBy: e,
  focusedDate: t,
  months: n,
  max: s,
  min: o,
  goto: r
}) {
  const a = e === "single" ? 1 : n, [u, f] = it(
    () => Ut(t.toPlainYearMonth(), n)
  ), l = (d) => f(Ut(u.start.add({ months: d }), n)), c = (d) => {
    const i = nt(u.start, d.toPlainYearMonth());
    return i >= 0 && i < n;
  };
  return L(() => {
    if (c(t))
      return;
    const d = nt(t.toPlainYearMonth(), u.start);
    r(t.add({ months: d }));
  }, [u.start]), L(() => {
    if (c(t))
      return;
    const d = nt(u.start, t.toPlainYearMonth());
    l(d === -1 ? -a : d === n ? a : Math.floor(d / n) * n);
  }, [t, a, n]), {
    page: u,
    previous: !o || !c(o) ? () => l(-a) : void 0,
    next: !s || !c(s) ? () => l(a) : void 0
  };
}
function bt({
  months: e,
  pageBy: t,
  locale: n,
  focusedDate: s,
  setFocusedDate: o
}) {
  const [r] = P("min"), [a] = P("max"), [u] = P("today"), f = N("focusday"), l = N("change"), c = w(
    () => Z(s ?? u ?? ht(), r, a),
    [s, u, r, a]
  );
  function d(p) {
    o(p), f(E(p));
  }
  const { next: i, previous: m, page: g } = en({
    pageBy: t,
    focusedDate: c,
    months: e,
    min: r,
    max: a,
    goto: d
  }), b = W();
  function y(p) {
    const v = p?.target ?? "day";
    v === "day" ? b.current.querySelectorAll("calendar-month").forEach((X) => X.focus(p)) : b.current.shadowRoot.querySelector(`[part~='${v}']`).focus(p);
  }
  return {
    format: $(Ve, n),
    formatVerbose: $(tn, n),
    page: g,
    focusedDate: c,
    dispatch: l,
    onFocus(p) {
      p.stopPropagation(), d(p.detail), setTimeout(y);
    },
    min: r,
    max: a,
    today: u,
    next: i,
    previous: m,
    focus: y
  };
}
const nn = k(
  (e) => {
    const [t, n] = P("value"), [s = t, o] = P("focusedDate"), r = bt({
      ...e,
      focusedDate: s,
      setFocusedDate: o
    });
    function a(u) {
      n(u.detail), r.dispatch();
    }
    return /* @__PURE__ */ h("host", { shadowDom: !0, focus: r.focus, children: /* @__PURE__ */ h(
      yt,
      {
        ...e,
        ...r,
        type: "date",
        value: t,
        onSelect: a
      }
    ) });
  },
  { props: pt, styles: gt }
);
customElements.define("calendar-date", nn);
function ee(e) {
  return /* @__PURE__ */ S(Jt, { children: [
    /* @__PURE__ */ h("label", { part: "label", for: "s", children: /* @__PURE__ */ h("slot", { name: "label", children: e.label }) }),
    /* @__PURE__ */ h("select", { id: "s", part: "select", onchange: e.onChange, children: e.options.map((t) => /* @__PURE__ */ h("option", { part: "option", ...t })) })
  ] });
}
const ne = [ft, dt];
function sn(e, t) {
  return Array.from({ length: e }, (n, s) => t(s));
}
function on(e) {
  const { min: t, max: n, focusedDate: s } = ut(_), o = N("focusday", { bubbles: !0 }), r = s.toPlainYearMonth(), a = r.year, u = Math.floor(e.maxYears / 2), f = a - u, l = a + (e.maxYears - u - 1), c = Math.max(f, t?.year ?? -1 / 0), d = Math.min(l, n?.year ?? 1 / 0), i = sn(d - c + 1, (g) => {
    const b = c + g;
    return {
      label: `${b}`,
      value: `${b}`,
      selected: b === r.year
    };
  });
  function m(g) {
    const y = parseInt(g.currentTarget.value) - r.year;
    o(s.add({ years: y }));
  }
  return { options: i, onChange: m };
}
const rn = k(
  (e) => {
    const t = on(e);
    return /* @__PURE__ */ h("host", { shadowDom: !0, children: /* @__PURE__ */ h(ee, { label: "Year", ...t }) });
  },
  {
    props: {
      maxYears: { type: Number, value: 20 }
    },
    styles: ne
  }
);
customElements.define("calendar-select-year", rn);
function an(e) {
  const { min: t, max: n, focusedDate: s, locale: o } = ut(_), r = N("focusday", { bubbles: !0 }), a = w(
    () => ({ month: e.formatMonth }),
    [e.formatMonth]
  ), u = $(a, o), f = w(() => {
    const i = [], m = /* @__PURE__ */ new Date();
    m.setUTCDate(1);
    for (var g = 0; g < 12; g++) {
      const b = (m.getUTCMonth() + 12) % 12;
      i[b] = u.format(m), m.setUTCMonth(m.getUTCMonth() + 1);
    }
    return i;
  }, [u]), l = s.toPlainYearMonth(), c = f.map((i, m) => {
    const g = m + 1, b = l.add({ months: g - l.month }), y = t != null && U.compare(b, t) < 0 || n != null && U.compare(b, n) > 0;
    return {
      label: i,
      value: `${g}`,
      disabled: y,
      selected: g === l.month
    };
  });
  function d(i) {
    const g = parseInt(i.currentTarget.value) - l.month;
    r(s.add({ months: g }));
  }
  return { options: c, onChange: d };
}
const cn = k(
  (e) => {
    const t = an(e);
    return /* @__PURE__ */ h("host", { shadowDom: !0, children: /* @__PURE__ */ h(ee, { label: "Month", ...t }) });
  },
  {
    props: {
      formatMonth: {
        type: String,
        value: () => "long"
      }
    },
    styles: ne
  }
);
customElements.define("calendar-select-month", cn);
const $t = (e, t) => C.compare(e, t) < 0 ? [e, t] : [t, e], ln = k(
  (e) => {
    const [t, n] = He("value"), [s = t[0], o] = P("focusedDate"), r = bt({
      ...e,
      focusedDate: s,
      setFocusedDate: o
    }), a = N("rangestart"), u = N("rangeend"), [f, l] = P(
      "tentative"
    ), [c, d] = it();
    L(() => d(void 0), [f]);
    function i(y) {
      r.onFocus(y), m(y);
    }
    function m(y) {
      y.stopPropagation(), f && d(y.detail);
    }
    function g(y) {
      const p = y.detail;
      y.stopPropagation(), f ? (n($t(f, p)), l(void 0), u(E(p)), r.dispatch()) : (l(p), a(E(p)));
    }
    const b = f ? $t(f, c ?? f) : t;
    return /* @__PURE__ */ h("host", { shadowDom: !0, focus: r.focus, children: /* @__PURE__ */ h(
      yt,
      {
        ...e,
        ...r,
        type: "range",
        value: b,
        onFocus: i,
        onHover: m,
        onSelect: g
      }
    ) });
  },
  {
    props: {
      ...pt,
      tentative: {
        type: String,
        value: ""
      }
    },
    styles: gt
  }
);
customElements.define("calendar-range", ln);
const un = k(
  (e) => {
    const [t, n] = We("value"), [s = t[0], o] = P("focusedDate"), r = bt({
      ...e,
      focusedDate: s,
      setFocusedDate: o
    });
    function a(u) {
      const f = [...t], l = t.findIndex((c) => c.equals(u.detail));
      l < 0 ? f.push(u.detail) : f.splice(l, 1), n(f), r.dispatch();
    }
    return /* @__PURE__ */ h("host", { shadowDom: !0, focus: r.focus, children: /* @__PURE__ */ h(
      yt,
      {
        ...e,
        ...r,
        type: "multi",
        value: t,
        onSelect: a
      }
    ) });
  },
  { props: pt, styles: gt }
);
customElements.define("calendar-multi", un);
export {
  nn as CalendarDate,
  Qe as CalendarMonth,
  un as CalendarMulti,
  ln as CalendarRange,
  cn as CalendarSelectMonth,
  rn as CalendarSelectYear
};
