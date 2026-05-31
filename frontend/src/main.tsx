import React, { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Command,
  FileText,
  Folder,
  MessageSquare,
  PanelLeftClose,
  PanelRightClose,
  Plus,
  SendHorizontal,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import "./styles.css";

type Project = {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
};

type Session = {
  id: string;
  project_id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
};

type DocumentResource = {
  id: string;
  project_id: string;
  filename: string;
  status: string;
  created_at: string;
  updated_at: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type Source = {
  filename?: string;
  parent_id?: string;
};

type Bootstrap = {
  projects: Project[];
  selected_project_id: string;
  sessions: Session[];
  selected_session_id: string;
  documents: DocumentResource[];
  messages: ChatMessage[];
};

type PendingConfirmation = {
  title: string;
  description: string;
  confirmLabel: string;
  action: () => Promise<void>;
};

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const detail = await response.text();
    let message = detail || response.statusText;
    try {
      const parsed = JSON.parse(detail) as { detail?: string };
      message = parsed.detail || message;
    } catch {
      // Keep the raw response text when it is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function shortId(id: string) {
  return id.slice(0, 8);
}

const SUPPORTED_UPLOAD_EXTENSIONS = [".pdf", ".md", ".markdown"];

function isSupportedUpload(file: File) {
  const name = file.name.toLowerCase();
  return SUPPORTED_UPLOAD_EXTENSIONS.some((extension) => name.endsWith(extension));
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [documents, setDocuments] = useState<DocumentResource[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [sessionGroups, setSessionGroups] = useState<Record<string, Session[]>>({});
  const [expandedProjectIds, setExpandedProjectIds] = useState<Set<string>>(new Set());
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [projectName, setProjectName] = useState("");
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState("Ready");
  const [isSending, setIsSending] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [isProjectFormOpen, setIsProjectFormOpen] = useState(false);
  const [isLeftPanelCollapsed, setIsLeftPanelCollapsed] = useState(false);
  const [isRightPanelCollapsed, setIsRightPanelCollapsed] = useState(false);
  const [selectedUploadFiles, setSelectedUploadFiles] = useState<File[]>([]);
  const [isUploadDragActive, setIsUploadDragActive] = useState(false);
  const [confirmation, setConfirmation] = useState<PendingConfirmation | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const streamRef = useRef<EventSource | null>(null);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId),
    [projects, selectedProjectId],
  );
  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId),
    [sessions, selectedSessionId],
  );

  useEffect(() => {
    api<Bootstrap>("/api/bootstrap")
      .then(applyBootstrap)
      .catch((error) => setStatus(error.message));
    return () => streamRef.current?.close();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  function applyBootstrap(data: Bootstrap) {
    setProjects(data.projects);
    setSelectedProjectId(data.selected_project_id);
    setSessions(data.sessions);
    setSessionGroups((current) => ({ ...current, [data.selected_project_id]: data.sessions }));
    setExpandedProjectIds((current) => new Set([...current, data.selected_project_id]));
    setSelectedSessionId(data.selected_session_id);
    setDocuments(data.documents);
    setMessages(data.messages);
    setSources([]);
    setStatus("Ready");
  }

  async function refreshSessions(projectId = selectedProjectId) {
    if (!projectId) return;
    const data = await api<{ sessions: Session[] }>(`/api/projects/${projectId}/sessions`);
    if (projectId === selectedProjectId) {
      setSessions(data.sessions);
    }
    setSessionGroups((current) => ({ ...current, [projectId]: data.sessions }));
  }

  async function refreshDocuments(projectId = selectedProjectId) {
    if (!projectId) return;
    const data = await api<{ documents: DocumentResource[] }>(`/api/projects/${projectId}/documents`);
    setDocuments(data.documents);
  }

  async function selectProject(projectId: string) {
    setSelectedProjectId(projectId);
    setExpandedProjectIds((current) => new Set([...current, projectId]));
    setSources([]);
    setStatus("Loading project...");
    const sessionData = await api<{ sessions: Session[] }>(`/api/projects/${projectId}/sessions`);
    const sessionId = sessionData.sessions[0]?.id;
    setSessions(sessionData.sessions);
    setSessionGroups((current) => ({ ...current, [projectId]: sessionData.sessions }));
    setSelectedSessionId(sessionId || "");
    const [documentData, messageData] = await Promise.all([
      api<{ documents: DocumentResource[] }>(`/api/projects/${projectId}/documents`),
      sessionId ? api<{ messages: ChatMessage[] }>(`/api/sessions/${sessionId}/messages`) : Promise.resolve({ messages: [] }),
    ]);
    setDocuments(documentData.documents);
    setMessages(messageData.messages);
    setStatus("Ready");
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    setIsBusy(true);
    try {
      const data = await api<Bootstrap>("/api/projects", {
        method: "POST",
        body: JSON.stringify({ name: projectName.trim() || "Untitled Project" }),
      });
      setProjectName("");
      applyBootstrap(data);
      setIsProjectFormOpen(false);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not create project");
    } finally {
      setIsBusy(false);
    }
  }

  async function createSession(projectId = selectedProjectId) {
    if (!projectId) return;
    setIsBusy(true);
    try {
      const data = await api<{ sessions: Session[]; selected_session_id: string; messages: ChatMessage[] }>(
        `/api/projects/${projectId}/sessions`,
        { method: "POST" },
      );
      setSelectedProjectId(projectId);
      setSessions(data.sessions);
      setSessionGroups((current) => ({ ...current, [projectId]: data.sessions }));
      setExpandedProjectIds((current) => new Set([...current, projectId]));
      setSelectedSessionId(data.selected_session_id);
      setMessages(data.messages);
      setSources([]);
      const documentData = await api<{ documents: DocumentResource[] }>(`/api/projects/${projectId}/documents`);
      setDocuments(documentData.documents);
      setStatus("Ready");
    } finally {
      setIsBusy(false);
    }
  }

  async function selectSession(session: Session) {
    setSelectedProjectId(session.project_id);
    setSelectedSessionId(session.id);
    setExpandedProjectIds((current) => new Set([...current, session.project_id]));
    setSources([]);
    setStatus("Loading chat...");
    const [sessionData, documentData, messageData] = await Promise.all([
      api<{ sessions: Session[] }>(`/api/projects/${session.project_id}/sessions`),
      api<{ documents: DocumentResource[] }>(`/api/projects/${session.project_id}/documents`),
      api<{ messages: ChatMessage[] }>(`/api/sessions/${session.id}/messages`),
    ]);
    setSessions(sessionData.sessions);
    setSessionGroups((current) => ({ ...current, [session.project_id]: sessionData.sessions }));
    setDocuments(documentData.documents);
    setMessages(messageData.messages);
    setStatus("Ready");
  }

  async function toggleProject(projectId: string) {
    const isExpanded = expandedProjectIds.has(projectId);
    setExpandedProjectIds((current) => {
      const next = new Set(current);
      if (isExpanded) {
        next.delete(projectId);
      } else {
        next.add(projectId);
      }
      return next;
    });
    if (!isExpanded && !sessionGroups[projectId]) {
      const data = await api<{ sessions: Session[] }>(`/api/projects/${projectId}/sessions`);
      setSessionGroups((current) => ({ ...current, [projectId]: data.sessions }));
    }
  }

  function chooseUploadFiles(files: FileList | File[]) {
    const allFiles = Array.from(files);
    const supportedFiles = allFiles.filter(isSupportedUpload);
    setSelectedUploadFiles(supportedFiles);
    if (allFiles.length && supportedFiles.length !== allFiles.length) {
      setStatus("Only PDF and Markdown (.md/.markdown) files can be uploaded.");
    } else if (supportedFiles.length) {
      setStatus(`${supportedFiles.length} file${supportedFiles.length === 1 ? "" : "s"} ready to upload`);
    }
  }

  function handleUploadDrop(event: React.DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsUploadDragActive(false);
    if (event.dataTransfer.files.length) {
      chooseUploadFiles(event.dataTransfer.files);
    }
  }

  async function uploadDocuments() {
    if (!selectedProjectId || !selectedUploadFiles.length) return;
    const formData = new FormData();
    selectedUploadFiles.forEach((file) => formData.append("files", file, file.name));
    setIsBusy(true);
    setStatus("Uploading and indexing...");
    try {
      const data = await api<{ added: number; skipped: number; documents: DocumentResource[] }>(
        `/api/projects/${selectedProjectId}/documents`,
        { method: "POST", body: formData },
      );
      setDocuments(data.documents);
      setSelectedUploadFiles([]);
      setStatus(`Added ${data.added}, skipped ${data.skipped}`);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Upload failed");
    } finally {
      setIsBusy(false);
    }
  }

  async function runConfirmation() {
    if (!confirmation) return;
    const action = confirmation.action;
    setConfirmation(null);
    try {
      await action();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Action failed");
    }
  }

  function deleteDocument(document: DocumentResource) {
    setConfirmation({
      title: "Delete resource?",
      description: `${document.filename} will be removed from retrieval for this project. Existing chat text stays unchanged.`,
      confirmLabel: "Delete resource",
      action: async () => {
        setIsBusy(true);
        try {
          await api(`/api/documents/${document.id}`, { method: "DELETE" });
          await refreshDocuments();
          setSources([]);
          setStatus("Document deleted");
        } finally {
          setIsBusy(false);
        }
      },
    });
  }

  function deleteProject(project: Project) {
    setConfirmation({
      title: "Delete project?",
      description: `This deletes "${project.name}", including its chats, indexed resources, and stored retrieval data.`,
      confirmLabel: "Delete project",
      action: async () => {
        setIsBusy(true);
        try {
          const data = await api<Bootstrap>(`/api/projects/${project.id}`, { method: "DELETE" });
          applyBootstrap(data);
          setStatus("Project deleted");
        } catch (error) {
          setStatus(error instanceof Error ? error.message : "Could not delete project");
        } finally {
          setIsBusy(false);
        }
      },
    });
  }

  function deleteCurrentSession() {
    if (!selectedSessionId) return;
    const sessionId = selectedSessionId;
    const projectId = selectedProjectId;
    setConfirmation({
      title: "Delete chat?",
      description: `This removes "${selectedSession?.title || "this chat"}" from the current project.`,
      confirmLabel: "Delete chat",
      action: async () => {
        setIsBusy(true);
        try {
          const data = await api<{ sessions: Session[]; selected_session_id: string; messages: ChatMessage[] }>(
            `/api/sessions/${sessionId}`,
            { method: "DELETE" },
          );
          setSessions(data.sessions);
          setSessionGroups((current) => ({ ...current, [projectId]: data.sessions }));
          setSelectedSessionId(data.selected_session_id);
          setMessages(data.messages);
          setSources([]);
          setStatus("Chat deleted");
        } catch (error) {
          setStatus(error instanceof Error ? error.message : "Could not delete chat");
        } finally {
          setIsBusy(false);
        }
      },
    });
  }

  function addSource(source: Source) {
    setSources((existing) => {
      const key = `${source.filename || ""}:${source.parent_id || ""}`;
      if (existing.some((item) => `${item.filename || ""}:${item.parent_id || ""}` === key)) {
        return existing;
      }
      return [...existing, source];
    });
  }

  function startChat(text: string) {
    if (!text || !selectedProjectId || !selectedSessionId || isSending) return;

    streamRef.current?.close();
    setDraft("");
    setSources([]);
    setIsSending(true);
    setStatus("Thinking...");
    setMessages((current) => [...current, { role: "user", content: text }, { role: "assistant", content: "" }]);

    const params = new URLSearchParams({ message: text });
    const streamUrl = `/api/projects/${selectedProjectId}/sessions/${selectedSessionId}/chat/stream?${params}`;
    const stream = new EventSource(streamUrl);
    streamRef.current = stream;

    stream.addEventListener("history", (event) => {
      const data = JSON.parse((event as MessageEvent).data) as { messages: ChatMessage[] };
      setMessages([...data.messages, { role: "assistant", content: "" }]);
    });

    stream.addEventListener("assistant_delta", (event) => {
      const data = JSON.parse((event as MessageEvent).data) as { content: string };
      setMessages((current) => {
        const next = [...current];
        const last = next[next.length - 1];
        if (last?.role === "assistant") {
          next[next.length - 1] = { role: "assistant", content: data.content };
        } else {
          next.push({ role: "assistant", content: data.content });
        }
        return next;
      });
    });

    stream.addEventListener("status", (event) => {
      const data = JSON.parse((event as MessageEvent).data) as { title?: string; content?: string };
      setStatus(data.title || data.content || "Working...");
    });

    stream.addEventListener("source", (event) => {
      addSource(JSON.parse((event as MessageEvent).data) as Source);
    });

    stream.addEventListener("done", async (event) => {
      const data = JSON.parse((event as MessageEvent).data) as { messages: ChatMessage[] };
      setMessages(data.messages);
      setStatus("Ready");
      setIsSending(false);
      stream.close();
      await refreshSessions();
    });

    stream.addEventListener("error", (event) => {
      if ("data" in event && event.data) {
        const data = JSON.parse((event as MessageEvent).data) as { message: string };
        setStatus(data.message);
      } else {
        setStatus("Connection interrupted");
      }
      setIsSending(false);
      stream.close();
    });
  }

  function sendMessage(event: FormEvent) {
    event.preventDefault();
    startChat(draft.trim());
  }

  return (
    <main
      className={`app-shell ${isLeftPanelCollapsed ? "left-collapsed" : ""} ${
        isRightPanelCollapsed ? "right-collapsed" : ""
      }`}
    >
      <aside className="sidebar nav-sidebar">
        <div className="panel-rail">
          <button className="icon-button" onClick={() => setIsLeftPanelCollapsed(false)} aria-label="Expand projects panel">
            <Command size={16} />
          </button>
          <button
            className="icon-button"
            onClick={() => {
              setIsLeftPanelCollapsed(false);
              setIsProjectFormOpen(true);
            }}
            aria-label="New project"
          >
            <Plus size={16} />
          </button>
        </div>

        <div className="panel-content">
          <div className="panel-topbar">
            <div className="brand">
              <div className="brand-mark"><Command size={17} /></div>
              <div className="brand-copy">
                <div className="brand-title">Agentic Document Assistant</div>
                <div className="brand-subtitle">Private document intelligence</div>
              </div>
            </div>
            <button className="icon-button ghost" onClick={() => setIsLeftPanelCollapsed(true)} aria-label="Collapse projects panel">
              <PanelLeftClose size={16} />
            </button>
          </div>

          <section className="panel-section grow">
            <div className="section-header">
              <div>
                <div className="section-title">Projects</div>
                <div className="section-count">{projects.length} total</div>
              </div>
              <button
                className="icon-button"
                onClick={() => setIsProjectFormOpen((open) => !open)}
                aria-label="Add project"
                title="Add project"
              >
                <Plus size={16} />
              </button>
            </div>

            {isProjectFormOpen && (
              <form className="inline-create" onSubmit={createProject}>
                <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Project name" />
                <button className="primary compact" disabled={isBusy}>
                  Add
                </button>
              </form>
            )}

            <div className="project-tree">
              {projects.map((project) => {
                const projectSessions = sessionGroups[project.id] || (project.id === selectedProjectId ? sessions : []);
                const isExpanded = expandedProjectIds.has(project.id);
                const isSelectedProject = project.id === selectedProjectId;

                return (
                  <div className={`project-node ${isSelectedProject ? "active" : ""}`} key={project.id}>
                    <div className="project-row">
                      <button className="tree-toggle" onClick={() => toggleProject(project.id)} aria-label="Toggle project">
                        {isExpanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      </button>
                      <button className="project-button" onClick={() => selectProject(project.id)}>
                        <span className="row-title"><Folder size={13} />{project.name}</span>
                        <small>{shortId(project.id)}</small>
                      </button>
                      <button
                        className="icon-button micro"
                        onClick={() => createSession(project.id)}
                        disabled={isBusy}
                        aria-label={`New chat in ${project.name}`}
                        title="New chat"
                      >
                        <Plus size={14} />
                      </button>
                      <button
                        className="icon-button micro danger-icon"
                        onClick={() => deleteProject(project)}
                        disabled={isBusy}
                        aria-label={`Delete project ${project.name}`}
                        title="Delete project"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>

                    {isExpanded && (
                      <div className="session-branch">
                        {projectSessions.length === 0 ? (
                          <div className="tree-empty">No chats yet</div>
                        ) : (
                          projectSessions.map((session) => (
                            <button
                              className={`session-item ${session.id === selectedSessionId ? "active" : ""}`}
                              key={session.id}
                              onClick={() => selectSession(session)}
                            >
                              <span className="row-title"><MessageSquare size={13} />{session.title}</span>
                              <small>{session.message_count} messages</small>
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      </aside>

      <section className="chat-workspace">
        <header className="workspace-header">
          <div className="workspace-title">
            <div className="eyebrow">{selectedProject?.name || "Project"}</div>
            <h1><MessageSquare size={22} />{selectedSession?.title || "New Chat"}</h1>
          </div>
          <div className="workspace-actions">
            <div className="status-pill">{status}</div>
            <button
              className="icon-button danger-icon"
              onClick={deleteCurrentSession}
              disabled={isBusy || !selectedSessionId}
              aria-label="Delete current chat"
              title="Delete chat"
            >
              <Trash2 size={15} />
            </button>
          </div>
        </header>

        <div className="messages">
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="eyebrow">Document workspace</div>
              <h2>Interrogate the archive.</h2>
              <p>Upload PDFs or Markdown, then ask for summaries, comparisons, obligations, risks, or exact details from the indexed resources.</p>
            </div>
          ) : (
            messages.map((message, index) => (
              <article className={`message ${message.role}`} key={`${message.role}-${index}`}>
                <div className="message-role">{message.role === "user" ? "You" : "Assistant"}</div>
                <div className="message-content">{message.content || (message.role === "assistant" ? "..." : "")}</div>
              </article>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        <form className="composer" onSubmit={sendMessage}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                startChat(draft.trim());
              }
            }}
            placeholder="Ask about this project's resources"
            disabled={isSending}
          />
          <button className="primary send-button" disabled={isSending || !draft.trim()}>
            <SendHorizontal size={16} />
            Send
          </button>
        </form>
      </section>

      <aside className="sidebar resource-sidebar">
        <div className="panel-rail">
          <button className="icon-button" onClick={() => setIsRightPanelCollapsed(false)} aria-label="Expand resources panel">
            <FileText size={16} />
          </button>
          <div className="rail-count">{documents.length}</div>
        </div>

        <div className="panel-content">
          <div className="panel-topbar">
            <div>
              <div className="section-title">Resources</div>
              <div className="section-count">{documents.length} indexed</div>
            </div>
            <button className="icon-button ghost" onClick={() => setIsRightPanelCollapsed(true)} aria-label="Collapse resources panel">
              <PanelRightClose size={16} />
            </button>
          </div>

          <section className="panel-section">
            <label
              className={`upload-zone ${isUploadDragActive ? "drag-active" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setIsUploadDragActive(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setIsUploadDragActive(false)}
              onDrop={handleUploadDrop}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.md,.markdown,application/pdf,text/markdown,text/x-markdown"
                onChange={(event) => event.target.files && chooseUploadFiles(event.target.files)}
              />
              <span className="upload-zone-content">
                <UploadCloud size={26} />
                <strong>Drop evidence here</strong>
                <small>
                  {selectedUploadFiles.length
                    ? selectedUploadFiles.map((file) => file.name).join(", ")
                    : "PDF, .md, and .markdown files are supported"}
                </small>
              </span>
            </label>
            <button className="primary action-button" onClick={uploadDocuments} disabled={isBusy || !selectedProjectId || selectedUploadFiles.length === 0}>
              <UploadCloud size={15} />
              Index resources
            </button>
          </section>

          <section className="panel-section">
            <div className="section-header">
              <div>
                <div className="section-title">Knowledge base</div>
                <div className="section-count">{selectedProject?.name || "Current project"}</div>
              </div>
            </div>
            {documents.length === 0 ? (
              <div className="panel-empty">No resources indexed.</div>
            ) : (
              <div className="document-list">
                {documents.map((document) => (
                  <div className="document-item" key={document.id}>
                    <div className="document-meta">
                      <span className="row-title"><FileText size={13} />{document.filename}</span>
                      <small>{shortId(document.id)}</small>
                    </div>
                    <button
                      className="icon-button micro danger-icon"
                      onClick={() => deleteDocument(document)}
                      disabled={isBusy}
                      aria-label={`Delete ${document.filename}`}
                      title="Delete document"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="panel-section grow">
            <div className="section-title">Answer provenance</div>
            {sources.length === 0 ? (
              <div className="panel-empty">Sources from the latest answer will appear here.</div>
            ) : (
              <div className="source-list">
                {sources.map((source, index) => (
                  <div className="source-card" key={`${source.filename}-${source.parent_id}-${index}`}>
                    <strong>{source.filename || "Unknown file"}</strong>
                    {source.parent_id && <span>Parent {source.parent_id}</span>}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </aside>

      {confirmation && (
        <div className="confirm-overlay" role="presentation" onMouseDown={() => setConfirmation(null)}>
          <section
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="confirm-kicker">Destructive action</div>
            <h2 id="confirm-title">{confirmation.title}</h2>
            <p>{confirmation.description}</p>
            <div className="confirm-actions">
              <button onClick={() => setConfirmation(null)} disabled={isBusy}>
                Cancel
              </button>
              <button className="danger solid-danger" onClick={runConfirmation} disabled={isBusy}>
                <Trash2 size={14} />
                {confirmation.confirmLabel}
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
