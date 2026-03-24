import { useEffect, useMemo, useState } from 'react'
import { io } from 'socket.io-client'

const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:7272'
const socketUrl = import.meta.env.VITE_SOCKET_URL || apiUrl

export default function App() {
  const [setupStatus, setSetupStatus] = useState(null)
  const [setupError, setSetupError] = useState('')
  const [token, setToken] = useState(localStorage.getItem('dvdflix_token') || '')
  const [loginForm, setLoginForm] = useState({ username: '', password: '' })
  const [setupForm, setSetupForm] = useState({
    username: '',
    password: '',
    settings: {
      MOVIES_PATH: '/media/movies',
      TV_PATH: '/media/tvshows',
      TEMP_RIP_PATH: '/media/tmp',
      DRIVES: '',
      TMDB_API_KEY: '',
      OLLAMA_URL: 'http://ollama:11434',
      OLLAMA_MODEL: 'qwen2.5:7b',
      RUNTIME_TOLERANCE_MINUTES: '8',
      MAX_IDENTIFY_WORKERS: '1',
      DISC_CACHE_DB: '/app/data/disc_cache.db',
    },
  })
  const [settingsDraft, setSettingsDraft] = useState(null)
  const [capabilities, setCapabilities] = useState(null)
  const [message, setMessage] = useState('')
  const [health, setHealth] = useState(null)
  const [jobs, setJobs] = useState([])
  const [library, setLibrary] = useState({ movies: [], tvshows: [] })

  const socket = useMemo(() => io(socketUrl, { transports: ['websocket', 'polling'] }), [])

  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

  const refreshSetupStatus = async () => {
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
      setSetupError(`Could not reach backend at ${apiUrl} (${err.message}). Check VITE_API_URL and backend container status.`)
    }
  }

  const fetchAuthedData = async () => {
    const [healthRes, jobsRes, libraryRes, capRes, settingsRes] = await Promise.all([
      fetch(`${apiUrl}/api/health`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/jobs`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/library`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/capabilities`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/settings`, { headers: authHeaders }),
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
  }

  useEffect(() => {
    refreshSetupStatus()
  }, [])

  useEffect(() => {
    if (!token) {
      return
    }

    fetchAuthedData()

    socket.on('job_update', (job) => {
      setJobs((prev) => {
        const rest = prev.filter((j) => j.id !== job.id)
        return [job, ...rest]
      })
      fetch(`${apiUrl}/api/library`, { headers: authHeaders }).then((r) => r.json()).then(setLibrary)
    })

    return () => {
      socket.disconnect()
    }
  }, [socket, token])

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
      setMessage(data.error || 'Failed to save settings')
      return
    }
    setMessage('Settings saved')
    await fetchAuthedData()
  }

  if (!setupStatus) {
    return (
      <div className="page">
        <p>Loading setup status...</p>
        {setupError && <p className="err">{setupError}</p>}
        {setupError && <button onClick={refreshSetupStatus}>Retry</button>}
      </div>
    )
  }

  if (!setupStatus.configured) {
    return (
      <div className="page">
        <header className="hero">
          <h1>DVDFlix First-Run Setup</h1>
          <p>Create admin account and runtime settings. Docker device and volume permissions still come from Dockge.</p>
        </header>
        <section className="card">
          <h2>Admin Account</h2>
          <input placeholder="Username" value={setupForm.username} onChange={(e) => setSetupForm({ ...setupForm, username: e.target.value })} />
          <input type="password" placeholder="Password (min 8 chars)" value={setupForm.password} onChange={(e) => setSetupForm({ ...setupForm, password: e.target.value })} />
        </section>
        <section className="card">
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
          <input placeholder="Username" value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} />
          <input type="password" placeholder="Password" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} />
          <button onClick={login}>Log In</button>
          {message && <p>{message}</p>}
        </section>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="hero">
        <h1>DVDFlix</h1>
        <p>Drive-aware ripping dashboard with live job updates.</p>
        <button onClick={startAll}>Start All Drives</button>
      </header>

      <section className="card">
        <h2>System</h2>
        {!health && <p>Loading...</p>}
        {health && (
          <>
            <p>Movies: {health.movies_path}</p>
            <p>TV: {health.tv_path}</p>
            <div className="drive-grid">
              {health.drives.map((drive) => (
                <button key={drive} onClick={() => startDrive(drive)}>
                  Start {drive}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="card">
        <h2>Ripper Capabilities</h2>
        {!capabilities && <p>Loading...</p>}
        {capabilities && (
          <>
            <p>Tools: lsdvd={String(capabilities.tools?.lsdvd)}, makemkvcon={String(capabilities.tools?.makemkvcon)}, eject={String(capabilities.tools?.eject)}</p>
            <p>Drive map: {Object.entries(capabilities.drives || {}).map(([k, v]) => `${k}:${v}`).join(', ') || 'none'}</p>
            <p>Path checks: movies={String(capabilities.paths?.movies?.exists)} tv={String(capabilities.paths?.tv?.exists)} temp={String(capabilities.paths?.temp?.exists)}</p>
          </>
        )}
      </section>

      <section className="card">
        <h2>Settings</h2>
        {settingsDraft && Object.entries(settingsDraft).map(([key, value]) => (
          <label key={key} className="field">
            <span>{key}</span>
            <input
              value={value}
              onChange={(e) => setSettingsDraft({ ...settingsDraft, [key]: e.target.value })}
            />
          </label>
        ))}
        <button onClick={saveSettings}>Save Settings</button>
        {message && <p>{message}</p>}
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
