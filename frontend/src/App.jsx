import { useEffect, useMemo, useState } from 'react'
import { io } from 'socket.io-client'

const envApiUrl = import.meta.env.VITE_API_URL || ''
const envSocketUrl = import.meta.env.VITE_SOCKET_URL || ''

const pipelineStages = [
  'lsdvd scan for disc label, track durations, and audio languages',
  'Agent tools: search_disc_label, tmdb_search, search_dialogue, runtime checks',
  'Low confidence fallback: temp rip, subtitle extract/OCR, dialogue-assisted re-identification',
  'Validation: runtime tolerance and language alignment',
  'SQLite disc cache stores label-to-title mapping to avoid repeat identification',
]

const knownIssues = [
  'MATSHITA (/dev/sr0) may fail on some discs (code 11/segfault).',
  'Software eject can be unreliable; manual eject may be needed.',
  'lsdvd title indexing differs from makemkvcon; use makemkvcon all mode.',
  'PAL runtime variance handled with ±8 minute tolerance.',
  'Ollama identification should stay sequential to avoid GPU contention.',
]

export default function App() {
  const [apiUrlInput, setApiUrlInput] = useState(localStorage.getItem('dvdflix_api_url') || envApiUrl)
  const [socketUrlInput, setSocketUrlInput] = useState(localStorage.getItem('dvdflix_socket_url') || envSocketUrl)
  const [apiUrl, setApiUrl] = useState(localStorage.getItem('dvdflix_api_url') || envApiUrl)
  const [socketUrl, setSocketUrl] = useState(localStorage.getItem('dvdflix_socket_url') || envSocketUrl)
  const [setupStatus, setSetupStatus] = useState(null)
  const [setupError, setSetupError] = useState('')
  const [token, setToken] = useState(localStorage.getItem('dvdflix_token') || '')
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [setupForm, setSetupForm] = useState({
    username: '',
    password: '',
    settings: {
      MOVIES_PATH: '',
      TV_PATH: '',
      TEMP_RIP_PATH: '',
      DRIVES: '',
      TMDB_API_KEY: '',
      OLLAMA_URL: '',
      OLLAMA_MODEL: '',
      RUNTIME_TOLERANCE_MINUTES: '',
      MAX_IDENTIFY_WORKERS: '',
      DISC_CACHE_DB: '',
    },
    profile: {
      PROFILE_SERVER: '',
      PROFILE_STORAGE_ROOT: '',
      PROFILE_DRIVE_SR0: '',
      PROFILE_DRIVE_SR1: '',
      PROFILE_DRIVE_SR2: '',
      PROFILE_GPU: '',
      PROFILE_JELLYFIN_URL: '',
      PROFILE_OLLAMA_MODEL: '',
      PROFILE_NOTES: '',
    },
  })
  const [settingsDraft, setSettingsDraft] = useState(null)
  const [profileDraft, setProfileDraft] = useState({})
  const [capabilities, setCapabilities] = useState(null)
  const [message, setMessage] = useState('')
  const [health, setHealth] = useState(null)
  const [jobs, setJobs] = useState([])
  const [library, setLibrary] = useState({ movies: [], tvshows: [] })

  const effectiveSocketUrl = socketUrl || apiUrl
  const socket = useMemo(() => io(effectiveSocketUrl, { autoConnect: false, transports: ['websocket', 'polling'] }), [effectiveSocketUrl])
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

  const refreshSetupStatus = async () => {
    if (!apiUrl) {
      setSetupError('Backend URL is not configured. Enter API URL below (example: http://192.168.1.50:7272).')
      return
    }
    try {
      const resp = await fetch(`${apiUrl}/api/setup/status`)
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`)
      }
      const data = await resp.json()
      setSetupStatus(data)
      setSetupError('')
      if (data?.settings && !settingsDraft) {
        setSettingsDraft(data.settings)
      }
    } catch (err) {
      setSetupError(`Could not reach backend at ${apiUrl} (${err.message}). Check backend container/network.`)
    }
  }

  const fetchAuthedData = async () => {
    const [healthRes, jobsRes, libraryRes, capRes, settingsRes, profileRes] = await Promise.all([
      fetch(`${apiUrl}/api/health`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/jobs`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/library`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/capabilities`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/settings`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/profile`, { headers: authHeaders }),
    ])

    if (healthRes.status === 401) {
      setToken('')
      localStorage.removeItem('dvdflix_token')
      return
    }

    setHealth(await healthRes.json())
    setJobs((await jobsRes.json()).jobs || [])
    setLibrary(await libraryRes.json())
    setCapabilities(await capRes.json())

    const settingsData = await settingsRes.json()
    if (settingsData?.settings) {
      setSettingsDraft(settingsData.settings)
    }

    const profileData = await profileRes.json()
    if (profileData?.profile) {
      setProfileDraft(profileData.profile)
    }
  }

  useEffect(() => {
    if (!apiUrl) {
      return
    }
    refreshSetupStatus()
  }, [apiUrl])

  useEffect(() => {
    if (!token || !effectiveSocketUrl) {
      return
    }

    fetchAuthedData()
    socket.connect()

    socket.on('job_update', (job) => {
      setJobs((prev) => {
        const rest = prev.filter((j) => j.id !== job.id)
        return [job, ...rest]
      })
    })

    return () => {
      socket.disconnect()
    }
  }, [socket, token, effectiveSocketUrl])

  const applyBackendUrls = () => {
    const nextApi = (apiUrlInput || '').trim().replace(/\/$/, '')
    const nextSocket = (socketUrlInput || '').trim().replace(/\/$/, '')
    setApiUrl(nextApi)
    setSocketUrl(nextSocket)
    localStorage.setItem('dvdflix_api_url', nextApi)
    localStorage.setItem('dvdflix_socket_url', nextSocket)
    setSetupError('')
  }

  const login = async () => {
    const resp = await fetch(`${apiUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(loginForm),
    })
    const data = await resp.json()
    if (!resp.ok) {
      setMessage(data.error || 'Login failed')
      return
    }
    setToken(data.token)
    localStorage.setItem('dvdflix_token', data.token)
    setMessage('Login successful')
  }

  const initializeSetup = async () => {
    const resp = await fetch(`${apiUrl}/api/setup/initialize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(setupForm),
    })
    const data = await resp.json()
    if (!resp.ok) {
      setMessage(data.error || 'Setup failed')
      return
    }
    localStorage.setItem('dvdflix_token', data.token)
    setToken(data.token)
    setMessage('Setup complete')
    await refreshSetupStatus()
  }

  const startAll = async () => {
    await fetch(`${apiUrl}/api/jobs/start-all`, { method: 'POST', headers: authHeaders })
  }

  const startDrive = async (drive) => {
    await fetch(`${apiUrl}/api/jobs/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ drive }),
    })
  }

  const saveSettings = async () => {
    if (!settingsDraft) {
      return
    }
    const resp = await fetch(`${apiUrl}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(settingsDraft),
    })
    const data = await resp.json()
    if (!resp.ok) {
      setMessage(data.error || 'Failed to save runtime settings')
      return
    }
    setMessage('Runtime settings saved')
  }

  const saveProfile = async () => {
    const resp = await fetch(`${apiUrl}/api/profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(profileDraft),
    })
    const data = await resp.json()
    if (!resp.ok) {
      setMessage(data.error || 'Failed to save system profile')
      return
    }
    setMessage('System profile saved')
  }

  const boolBadge = (ok) => (
    <span className={`pill ${ok ? 'ok' : 'bad'}`}>{ok ? 'OK' : 'Missing'}</span>
  )

  if (!setupStatus) {
    return (
      <div className="page">
        <section className="card">
          <h2>Connection</h2>
          <label className="field">
            <span>Backend API URL</span>
            <input value={apiUrlInput} onChange={(e) => setApiUrlInput(e.target.value)} placeholder="http://192.168.1.50:7272" />
          </label>
          <label className="field">
            <span>Socket URL (optional)</span>
            <input value={socketUrlInput} onChange={(e) => setSocketUrlInput(e.target.value)} placeholder="http://192.168.1.50:7272" />
          </label>
          <button onClick={applyBackendUrls}>Save Connection</button>
          {setupError && <p className="err">{setupError}</p>}
          {setupError && <button onClick={refreshSetupStatus}>Retry</button>}
        </section>
      </div>
    )
  }

  if (!setupStatus.configured) {
    return (
      <div className="page">
        <header className="hero">
          <h1>DVDFlix First-Run Setup</h1>
          <p>Create admin account, runtime config, and system profile.</p>
        </header>
        <section className="card">
          <h2>Admin Account</h2>
          <label className="field">
            <span>Username</span>
            <input placeholder="admin" value={setupForm.username} onChange={(e) => setSetupForm({ ...setupForm, username: e.target.value })} />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" placeholder="min 8 characters" value={setupForm.password} onChange={(e) => setSetupForm({ ...setupForm, password: e.target.value })} />
          </label>
        </section>

        <section className="card two-col">
          <div>
            <h2>Runtime Settings</h2>
            {Object.entries(setupForm.settings).map(([key, value]) => (
              <label key={key} className="field">
                <span>{key}</span>
                <input
                  value={value}
                  onChange={(e) => setSetupForm({
                    ...setupForm,
                    settings: { ...setupForm.settings, [key]: e.target.value },
                  })}
                />
              </label>
            ))}
          </div>
          <div>
            <h2>System Profile</h2>
            {Object.entries(setupForm.profile).map(([key, value]) => (
              <label key={key} className="field">
                <span>{key}</span>
                <input
                  value={value}
                  onChange={(e) => setSetupForm({
                    ...setupForm,
                    profile: { ...setupForm.profile, [key]: e.target.value },
                  })}
                />
              </label>
            ))}
          </div>
        </section>

        <section className="card">
          <button onClick={initializeSetup}>Complete Setup</button>
          {message && <p>{message}</p>}
        </section>
      </div>
    )
  }

  if (!token) {
    return (
      <div className="page">
        <header className="hero">
          <h1>DVDFlix Login</h1>
        </header>
        <section className="card">
          <label className="field">
            <span>Username</span>
            <input placeholder="Username" value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" placeholder="Password" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} />
          </label>
          <button onClick={login}>Log In</button>
          {message && <p>{message}</p>}
        </section>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="hero">
        <h1>DVDFlix Operations</h1>
        <p>Ripping pipeline visibility, profile tracking, and live job control.</p>
        <button onClick={startAll}>Start All Drives</button>
      </header>

      <section className="card two-col">
        <div>
          <h2>Runtime Snapshot</h2>
          {!health && <p>Loading...</p>}
          {health && (
            <div className="kv-list">
              <p><strong>Movies:</strong> {health.movies_path}</p>
              <p><strong>TV:</strong> {health.tv_path}</p>
              <p><strong>Drives:</strong> {health.drives.join(', ') || 'none'}</p>
            </div>
          )}
          <div className="drive-grid">
            {(health?.drives || []).map((drive) => (
              <button key={drive} onClick={() => startDrive(drive)}>Start {drive}</button>
            ))}
          </div>
        </div>
        <div>
          <h2>Ripper Capabilities</h2>
          {!capabilities && <p>Loading...</p>}
          {capabilities && (
            <div className="status-grid">
              <p>lsdvd {boolBadge(capabilities.tools?.lsdvd)}</p>
              <p>makemkvcon {boolBadge(capabilities.tools?.makemkvcon)}</p>
              <p>eject {boolBadge(capabilities.tools?.eject)}</p>
              {Object.entries(capabilities.drives || {}).map(([drive, ok]) => (
                <p key={drive}>{drive} {boolBadge(ok)}</p>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="card two-col">
        <div>
          <h2>System Profile</h2>
          {Object.entries(profileDraft || {}).map(([key, value]) => (
            <label key={key} className="field">
              <span>{key}</span>
              <input value={value || ''} onChange={(e) => setProfileDraft({ ...profileDraft, [key]: e.target.value })} />
            </label>
          ))}
          <button onClick={saveProfile}>Save System Profile</button>
        </div>
        <div>
          <h2>Runtime Settings</h2>
          {settingsDraft && Object.entries(settingsDraft).map(([key, value]) => (
            <label key={key} className="field">
              <span>{key}</span>
              <input value={value} onChange={(e) => setSettingsDraft({ ...settingsDraft, [key]: e.target.value })} />
            </label>
          ))}
          <button onClick={saveSettings}>Save Runtime Settings</button>
          {message && <p>{message}</p>}
        </div>
      </section>

      <section className="card two-col">
        <div>
          <h2>Identification Pipeline</h2>
          <ul>
            {pipelineStages.map((stage) => <li key={stage}>{stage}</li>)}
          </ul>
        </div>
        <div>
          <h2>Known Decisions</h2>
          <ul>
            {knownIssues.map((issue) => <li key={issue}>{issue}</li>)}
          </ul>
        </div>
      </section>

      <section className="card">
        <h2>Recent Jobs</h2>
        {jobs.length === 0 && <p>No jobs yet.</p>}
        {jobs.map((job) => (
          <article key={job.id} className="job">
            <p><strong>{job.drive}</strong> - {job.state}</p>
            <p>{job.title || job.disc_label || 'Unknown disc'}</p>
            {job.output_path && <p>Output: {job.output_path}</p>}
            {job.error && <p className="err">Error: {job.error}</p>}
          </article>
        ))}
      </section>

      <section className="card two-col">
        <div>
          <h2>Movies</h2>
          <ul>
            {library.movies.slice(0, 100).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
        <div>
          <h2>TV Shows</h2>
          <ul>
            {library.tvshows.slice(0, 100).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </section>
    </div>
  )
}
