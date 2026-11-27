import { useEffect, useState } from "react";
import type { Gate } from "../App";
import { api, setAuth, authToken } from "../api";

type Person = { id: string; username: string; admin: boolean };

export function AccountPage({ gate, onUser }: { gate: Gate; onUser: (username: string) => void }) {
  const [me, setMe] = useState<Person | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [username, setUsername] = useState("");
  const [usernamePassword, setUsernamePassword] = useState("");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [again, setAgain] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, { username: string; password: string }>>({});
  const [busy, setBusy] = useState("");

  async function load() {
    const current = await api<Person>("/api/auth/me");
    setMe(current);
    setUsername(current.username);
    if (!current.admin) return;
    const rows = await api<Person[]>("/api/users");
    setPeople(rows);
    setDrafts(Object.fromEntries(rows.map((item) => [item.id, { username: item.username, password: "" }])));
  }

  useEffect(() => {
    load().catch((error) => gate.report(error));
  }, []);

  async function saveUsername() {
    if (!username.trim() || !usernamePassword) {
      gate.report(new Error("新用户名和当前密码都要填。"));
      return;
    }
    setSavingName(true);
    try {
      const updated = await api<Person>("/api/auth/username", {
        method: "POST",
        body: JSON.stringify({ username: username.trim(), password: usernamePassword }),
      });
      setAuth(authToken(), updated.username, updated.admin);
      setMe(updated);
      setUsernamePassword("");
      onUser(updated.username);
      gate.report("");
      if (updated.admin) await load();
    } catch (error) {
      gate.report(error);
    } finally {
      setSavingName(false);
    }
  }

  async function savePassword() {
    if (!oldPassword || !newPassword) {
      gate.report(new Error("当前密码和新密码都要填。"));
      return;
    }
    if (newPassword !== again) {
      gate.report(new Error("两次输入的新密码不一致。"));
      return;
    }
    setSavingPassword(true);
    try {
      await api("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      });
      setOldPassword("");
      setNewPassword("");
      setAgain("");
      gate.report("");
    } catch (error) {
      gate.report(error);
    } finally {
      setSavingPassword(false);
    }
  }

  function draftOf(id: string) {
    return drafts[id] || { username: "", password: "" };
  }

  async function savePerson(person: Person, field: "username" | "password") {
    const draft = draftOf(person.id);
    const payload = field === "username" ? { username: draft.username.trim() } : { password: draft.password };
    if (field === "username" && !payload.username) {
      gate.report(new Error("用户名不能空。"));
      return;
    }
    if (field === "password" && !draft.password) {
      gate.report(new Error("新密码不能空。"));
      return;
    }
    setBusy(`${person.id}:${field}`);
    try {
      const updated = await api<Person>(`/api/users/${person.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      if (updated.id === me?.id) {
        setAuth(authToken(), updated.username, updated.admin);
        onUser(updated.username);
      }
      gate.report("");
      await load();
    } catch (error) {
      gate.report(error);
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="stack">
      <section className="card stack">
        <h2>我的账号</h2>
        <p className="hint">改用户名不换账本。账本跟着用户号，持仓和现金都还在。</p>
        <label>用户名
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>当前密码
          <input type="password" value={usernamePassword} onChange={(event) => setUsernamePassword(event.target.value)} />
        </label>
        <button className="btn" type="button" disabled={savingName} onClick={saveUsername}>{savingName ? "保存中…" : "保存用户名"}</button>
      </section>
      <section className="card stack">
        <h2>修改密码</h2>
        <label>当前密码
          <input type="password" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} />
        </label>
        <label>新密码
          <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
        </label>
        <label>再输一次
          <input type="password" value={again} onChange={(event) => setAgain(event.target.value)} />
        </label>
        <p className="hint">至少 6 位。改完之后，其他设备上的登录会退出。</p>
        <button className="btn" type="button" disabled={savingPassword} onClick={savePassword}>{savingPassword ? "保存中…" : "修改密码"}</button>
      </section>
      {me?.admin ? (
        <section className="card">
          <h2>用户</h2>
          <p className="hint">管理员可以改别人的用户名，或直接重置密码。重置后对方需要用新密码登录。</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>用户名</th><th>身份</th><th>改用户名</th><th>重置密码</th></tr>
              </thead>
              <tbody>
                {people.map((person) => {
                  const draft = draftOf(person.id);
                  const mine = person.id === me.id;
                  return (
                    <tr key={person.id}>
                      <td>{person.username}</td>
                      <td>{person.admin ? "管理员" : "用户"}</td>
                      <td>
                        <div className="row">
                          <input value={draft.username} onChange={(event) => setDrafts((current) => ({ ...current, [person.id]: { ...draft, username: event.target.value } }))} />
                          <button className="btn secondary" type="button" disabled={busy === `${person.id}:username`} onClick={() => savePerson(person, "username")}>保存</button>
                        </div>
                      </td>
                      <td>
                        {mine ? <span className="hint">用上面的表单</span> : (
                          <div className="row">
                            <input type="password" value={draft.password} placeholder="新密码" onChange={(event) => setDrafts((current) => ({ ...current, [person.id]: { ...draft, password: event.target.value } }))} />
                            <button className="btn secondary" type="button" disabled={busy === `${person.id}:password`} onClick={() => savePerson(person, "password")}>重置</button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
