import { useEffect, useMemo, useState } from 'react'
import { io } from 'socket.io-client'

const envApiUrl = import.meta.env.VITE_API_URL || ''
const envSocketUrl = import.meta.env.VITE_SOCKET_URL || ''

const pages = ['dashboard', 'ripper-status', 'settings', 'library', 'history', 'accounts']

const pipelineStages = [
  'lsdvd scan for disc label, track durations, and audio languages',
  'LLM proposes likely title/year, then TMDB candidates are hydrated with runtime metadata',
  'Cross-check scoring validates runtime, label overlap, and optional OMDB/TVDB corroboration',
  'Low-confidence results fall back to conservative LLM naming to avoid false positives',
  'SQLite disc cache stores label-to-title mapping to avoid repeat identification',
]

export default function App() {
  const [apiUrl, setApiUrl] = useState(localStorage.getItem('dvdflix_api_url') || envApiUrl)
  const [socketUrl, setSocketUrl] = useState(localStorage.getItem('dvdflix_socket_url') || envSocketUrl)
  const [apiUrlInput, setApiUrlInput] = useState(apiUrl)
  const [socketUrlInput, setSocketUrlInput] = useState(socketUrl)
  const [theme, setTheme] = useState(localStorage.getItem('dvdflix_theme') || 'dark')
  const [activePage, setActivePage] = useState('dashboard')

  const [setupStatus, setSetupStatus] = useState(null)
  const [setupError, setSetupError] = useState('')
  const [detectedDrives, setDetectedDrives] = useState([])
  const [manualSetupDrives, setManualSetupDrives] = useState(false)
  const [manualSettingsDrives, setManualSettingsDrives] = useState(false)
  const [token, setToken] = useState(localStorage.getItem('dvdflix_token') || '')
  const [message, setMessage] = useState('')
  const [messageType, setMessageType] = useState('') // 'success', 'error', 'info'

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
      OMDB_API_KEY: '',
      TVDB_API_KEY: '',
      TVDB_PIN: '',
      OLLAMA_URL: 'http://host.docker.internal:11434',
      OLLAMA_MODEL: 'qwen2.5:7b',
      RUNTIME_TOLERANCE_MINUTES: '8',
      IDENTIFY_MIN_CONFIDENCE: '80',
      MAX_IDENTIFY_WORKERS: '1',
      DISC_CACHE_DB: '/app/data/disc_cache.db',
      OPENSUBTITLES_API_KEY: '',
      ENABLE_WEB_SEARCH: 'false',
      SEARXNG_URL: '',
      HANDBRAKE_PRESET: 'default',
      MAKEMKVCON_PATH: 'makemkvcon',
    },
    profile: {
      PROFILE_SERVER: '',
      PROFILE_STORAGE_ROOT: '',
      PROFILE_DRIVE_SR0: 'SR0',
      PROFILE_DRIVE_SR1: 'SR1',
      PROFILE_DRIVE_SR2: 'SR2',
      PROFILE_GPU: 'CPU',
      PROFILE_JELLYFIN_URL: '',
      PROFILE_OLLAMA_MODEL: 'qwen2.5:7b',
      PROFILE_NOTES: '',
    },
  })

  const [settingsDraft, setSettingsDraft] = useState(null)
  const [profileDraft, setProfileDraft] = useState({})
  const [capabilities, setCapabilities] = useState(null)
  const [health, setHealth] = useState(null)
  const [jobs, setJobs] = useState([])
  const [library, setLibrary] = useState({ movies: [], tvshows: [] })
  const [history, setHistory] = useState([])
  const [accounts, setAccounts] = useState([])
  const [currentUser, setCurrentUser] = useState(null)
  const [newAccountForm, setNewAccountForm] = useState({ username: '', password: '', is_admin: false })
  
  // Manual title override modal
  const [overrideModal, setOverrideModal] = useState(null) // { jobId, jobTitle }
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [historyEditModal, setHistoryEditModal] = useState(null)

  const effectiveSocketUrl = socketUrl || apiUrl
  const socket = useMemo(() => io(effectiveSocketUrl, { autoConnect: false, transports: ['websocket', 'polling'] }), [effectiveSocketUrl])
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : {}

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('dvdflix_theme', theme)
  }, [theme])

  const showMessage = (text, type = 'info') => {
    setMessage(text)
    setMessageType(type)
    setTimeout(() => setMessage(''), 5000)
  }

  const refreshSetupStatus = async () => {
    if (!apiUrl) {
      showMessage('Backend URL is required', 'error')
      return
    }
    try {
      const resp = await fetch(`${apiUrl}/api/setup/status`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setSetupStatus(data)
      setSetupError('')
      setDetectedDrives(data?.detected_drives || [])
      if (data?.settings && !settingsDraft) {
        setSettingsDraft(data.settings)
      }
    } catch (err) {
      setSetupError(`Cannot reach ${apiUrl}: ${err.message}`)
    }
  }

  const fetchAuthedData = async () => {
    const [healthRes, jobsRes, libraryRes, capRes, settingsRes, profileRes, historyRes, accountsRes] = await Promise.all([
      fetch(`${apiUrl}/api/health`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/jobs`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/library`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/capabilities`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/settings`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/profile`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/history?limit=500`, { headers: authHeaders }),
      fetch(`${apiUrl}/api/accounts`, { headers: authHeaders }),
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
    if (settingsData?.settings) setSettingsDraft(settingsData.settings)

    const profileData = await profileRes.json()
    if (profileData?.profile) setProfileDraft(profileData.profile)

    const historyData = await historyRes.json()
    setHistory(historyData?.history || [])

    const accountsData = await accountsRes.json()
    setAccounts(accountsData?.users || [])
    setCurrentUser(accountsData?.current_user || null)
  }

  useEffect(() => {
    if (apiUrl) refreshSetupStatus()
  }, [apiUrl])

  useEffect(() => {
    if (!token || !effectiveSocketUrl) return
    fetchAuthedData()
    socket.connect()
    socket.on('job_update', (job) => {
      setJobs((prev) => {
        const rest = prev.filter((j) => j.id !== job.id)
        return [job, ...rest]
      })
    })
    return () => socket.disconnect()
  }, [socket, token, effectiveSocketUrl])

  const applyBackendUrls = () => {
    const nextApi = (apiUrlInput || '').trim().replace(/\/$/, '')
    const nextSocket = (socketUrlInput || '').trim().replace(/\/$/, '')
    setApiUrl(nextApi)
    setSocketUrl(nextSocket)
    localStorage.setItem('dvdflix_api_url', nextApi)
    localStorage.setItem('dvdflix_socket_url', nextSocket)
  }

  const login = async () => {
    const resp = await fetch(`${apiUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(loginForm),
    })
    const data = await resp.json()
    if (!resp.ok) {
      showMessage(data.error || 'Login failed', 'error')
      return
    }
    setToken(data.token)
    localStorage.setItem('dvdflix_token', data.token)
    showMessage('Login successful', 'success')
  }

  const initializeSetup = async () => {
    const resp = await fetch(`${apiUrl}/api/setup/initialize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(setupForm),
    })
    const data = await resp.json()
    if (!resp.ok) {
      showMessage(data.error || 'Setup failed', 'error')
      return
    }
    localStorage.setItem('dvdflix_token', data.token)
    setToken(data.token)
    showMessage('Setup complete', 'success')
    await refreshSetupStatus()
  }

  const detectDrives = async () => {
    try {
      const resp = await fetch(`${apiUrl}/api/setup/detected-drives`)
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      const drives = data?.drives || []
      setDetectedDrives(drives)
      if (drives.length === 0) {
        setManualSetupDrives(true)
        setManualSettingsDrives(true)
        showMessage('No drives detected inside container. Check Docker device mapping.', 'info')
      } else {
        setManualSetupDrives(false)
        setManualSettingsDrives(false)
        showMessage(`Detected ${drives.length} drive(s)`, 'success')
      }
    } catch (err) {
      showMessage(`Drive detection failed: ${err.message}`, 'error')
    }
  }

  const saveSettings = async () => {
    if (!settingsDraft) return
    const resp = await fetch(`${apiUrl}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(settingsDraft),
    })
    showMessage(resp.ok ? 'Settings saved' : 'Failed to save', resp.ok ? 'success' : 'error')
  }

  const startAll = async () => {
    await fetch(`${apiUrl}/api/jobs/start-all`, { method: 'POST', headers: authHeaders })
    showMessage('Started all drives', 'success')
  }

  const startDrive = async (drive) => {
    const resp = await fetch(`${apiUrl}/api/jobs/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ drive }),
    })
    showMessage(resp.ok ? `Started ${drive}` : 'Error', resp.ok ? 'success' : 'error')
  }

  const searchTMDB = async (query, mediaType = 'movie') => {
    setSearching(true)
    try {
      const resp = await fetch(`${apiUrl}/api/search/tmdb`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders },
        body: JSON.stringify({ query, media_type: mediaType }),
      })
      const data = await resp.json()
      setSearchResults(data.ok ? (data.results || []) : [])
      if (!data.ok) showMessage(data.error || 'Search failed', 'error')
    } catch (err) {
      showMessage('Search error: ' + err.message, 'error')
    } finally {
      setSearching(false)
    }
  }

  const overrideJobTitle = async (jobId, title, year, mediaType) => {
    const resp = await fetch(`${apiUrl}/api/jobs/${jobId}/override-title`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify({ title, year, media_type: mediaType }),
    })
    if (resp.ok) {
      showMessage('Title overridden successfully', 'success')
      setOverrideModal(null)
      setSearchQuery('')
      setSearchResults([])
    } else {
      showMessage('Failed to override title', 'error')
    }
  }

  const saveHistoryCorrection = async () => {
    if (!historyEditModal) return
    const payload = {
      title: historyEditModal.title || '',
      year: historyEditModal.year || '',
      media_type: historyEditModal.media_type || 'movie',
      notes: historyEditModal.notes || '',
    }
    const resp = await fetch(`${apiUrl}/api/history/${historyEditModal.disc_hash}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}))
      showMessage(data.error || 'Failed to update history record', 'error')
      return
    }
    showMessage('History record updated', 'success')
    setHistoryEditModal(null)
    await fetchAuthedData()
  }

  const createAccount = async () => {
    const payload = {
      username: (newAccountForm.username || '').trim(),
      password: newAccountForm.password || '',
      is_admin: !!newAccountForm.is_admin,
    }
    if (!payload.username || !payload.password) {
      showMessage('Username and password are required', 'error')
      return
    }

    const resp = await fetch(`${apiUrl}/api/accounts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(payload),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      showMessage(data.error || 'Failed to create account', 'error')
      return
    }
    showMessage('Account created', 'success')
    setNewAccountForm({ username: '', password: '', is_admin: false })
    await fetchAuthedData()
  }

  const logout = () => {
    setToken('')
    localStorage.removeItem('dvdflix_token')
    showMessage('Logged out', 'info')
  }

  const jobStateColor = (state) => {
    switch (state) {
      case 'complete': return '#10b981'
      case 'failed': return '#ef4444'
      case 'ripping': return '#f59e0b'
      case 'identifying': return '#3b82f6'
      case 'pending': return '#6b7280'
      default: return '#999'
    }
  }

  // Connection Setup Page
  if (!setupStatus) {
    return (
      <div className="page setup-page">
        <div className="setup-container">
          <div className="setup-header">
            <h1>🎬 DVDFlix</h1>
            <p>Self-hosted DVD Operations Console</p>
          </div>
          
          <div className="setup-card">
            <h2>Backend Connection</h2>
            <div className="form-group">
              <label>API URL</label>
              <input 
                type="text"
                placeholder="http://localhost:7272"
                value={apiUrlInput}
                onChange={(e) => setApiUrlInput(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label>Socket URL (optional)</label>
              <input 
                type="text"
                placeholder="Leave empty to use API URL"
                value={socketUrlInput}
                onChange={(e) => setSocketUrlInput(e.target.value)}
              />
            </div>
            <button className="btn-primary" onClick={applyBackendUrls}>
              Connect
            </button>
            {setupError && <div className="alert alert-error">{setupError}</div>}
          </div>
        </div>
      </div>
    )
  }

  // First-Run Setup
  if (!setupStatus.configured) {
    return (
      <div className="page setup-page">
        <div className="setup-container">
          <div className="setup-header">
            <h1>🎬 DVDFlix Setup</h1>
            <p>Configure Your Ripping System</p>
          </div>

          <div className="setup-card">
            <h2>Admin Account</h2>
            <div className="form-group">
              <label>Username</label>
              <input value={setupForm.username} onChange={(e) => setSetupForm({ ...setupForm, username: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input type="password" value={setupForm.password} onChange={(e) => setSetupForm({ ...setupForm, password: e.target.value })} />
            </div>
          </div>

          <div className="setup-cards-row">
            <div className="setup-card">
              <h2>🔧 Runtime Settings</h2>
              <div className="form-group">
                <label>Movies Path</label>
                <input value={setupForm.settings.MOVIES_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, MOVIES_PATH: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TV Path</label>
                <input value={setupForm.settings.TV_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TV_PATH: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Temp Rip Path</label>
                <input value={setupForm.settings.TEMP_RIP_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TEMP_RIP_PATH: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TMDB API Key</label>
                <input type="password" value={setupForm.settings.TMDB_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TMDB_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>OMDB API Key</label>
                <input type="password" value={setupForm.settings.OMDB_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OMDB_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TVDB API Key</label>
                <input type="password" value={setupForm.settings.TVDB_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TVDB_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>TVDB PIN</label>
                <input value={setupForm.settings.TVDB_PIN} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, TVDB_PIN: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>OpenSubtitles API Key</label>
                <input type="password" value={setupForm.settings.OPENSUBTITLES_API_KEY} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OPENSUBTITLES_API_KEY: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Drives (Auto-Detect)</label>
                <div className="inline-actions">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={detectDrives}
                  >
                    Detect Drives
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() =>
                      setSetupForm({
                        ...setupForm,
                        settings: {
                          ...setupForm.settings,
                          DRIVES: detectedDrives.join(','),
                        },
                      })
                    }
                    disabled={detectedDrives.length === 0}
                  >
                    Use Detected
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => setManualSetupDrives((v) => !v)}
                  >
                    {manualSetupDrives ? 'Hide Manual Entry' : 'Manual Entry'}
                  </button>
                </div>
                {manualSetupDrives && (
                  <input
                    placeholder="/dev/sr0,/dev/sr1"
                    value={setupForm.settings.DRIVES}
                    onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, DRIVES: e.target.value } })}
                  />
                )}
                <small className="field-help">
                  Leave blank to auto-detect `/dev/sr*` drives. Detected now: {detectedDrives.length ? detectedDrives.join(', ') : 'none'}
                </small>
              </div>
            </div>

            <div className="setup-card">
              <h2>🌐 Ollama Settings</h2>
              <div className="form-group">
                <label>Ollama URL</label>
                <input value={setupForm.settings.OLLAMA_URL} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OLLAMA_URL: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Ollama Model</label>
                <input value={setupForm.settings.OLLAMA_MODEL} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, OLLAMA_MODEL: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Confidence Threshold</label>
                <input type="number" min="0" max="100" value={setupForm.settings.IDENTIFY_MIN_CONFIDENCE} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, IDENTIFY_MIN_CONFIDENCE: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Runtime Tolerance Minutes</label>
                <input type="number" min="0" max="60" value={setupForm.settings.RUNTIME_TOLERANCE_MINUTES} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, RUNTIME_TOLERANCE_MINUTES: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Max Identify Workers</label>
                <input type="number" min="1" max="8" value={setupForm.settings.MAX_IDENTIFY_WORKERS} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, MAX_IDENTIFY_WORKERS: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Disc Cache DB Path</label>
                <input value={setupForm.settings.DISC_CACHE_DB} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, DISC_CACHE_DB: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>Enable Web Search</label>
                <select value={setupForm.settings.ENABLE_WEB_SEARCH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, ENABLE_WEB_SEARCH: e.target.value } })}>
                  <option value="false">false</option>
                  <option value="true">true</option>
                </select>
              </div>
              <div className="form-group">
                <label>Searxng URL</label>
                <input value={setupForm.settings.SEARXNG_URL} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, SEARXNG_URL: e.target.value } })} />
              </div>
              <div className="form-group">
                <label>HandBrake Preset</label>
                <select value={setupForm.settings.HANDBRAKE_PRESET} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, HANDBRAKE_PRESET: e.target.value } })}>
                  <option value="default">default (all tracks)</option>
                  <option value="standard">standard (main feature)</option>
                </select>
              </div>
              <div className="form-group">
                <label>MakeMKV Command Path</label>
                <input value={setupForm.settings.MAKEMKVCON_PATH} onChange={(e) => setSetupForm({ ...setupForm, settings: { ...setupForm.settings, MAKEMKVCON_PATH: e.target.value } })} />
                <small className="field-help">Default: `makemkvcon`</small>
              </div>
            </div>
          </div>

          <div className="setup-card">
            <h2>ℹ️ Docker-Level Requirements</h2>
            <p className="field-help">
              Keys and runtime behavior are fully configurable in this UI. Docker still needs host-level mappings for optical devices and media folders.
            </p>
            <p className="field-help">
              Required at deploy time in Dockge: `HOST_MOVIES_PATH`, `HOST_TV_PATH`, `HOST_TEMP_RIP_PATH`, and `/dev/sr*` device mapping.
            </p>
          </div>

          <button className="btn-primary full-width" onClick={initializeSetup}>
            Complete Setup
          </button>
          {message && <div className={`alert alert-${messageType}`}>{message}</div>}
        </div>
      </div>
    )
  }

  // Login
  if (!token) {
    return (
      <div className="page setup-page">
        <div className="setup-container">
          <div className="setup-header">
            <h1>🔐 DVDFlix Login</h1>
            <p>Enter your credentials</p>
          </div>

          <div className="setup-card">
            <div className="form-group">
              <label>Username</label>
              <input value={loginForm.username} onChange={(e) => setLoginForm({ ...loginForm, username: e.target.value })} />
            </div>
            <div className="form-group">
              <label>Password</label>
              <input type="password" value={loginForm.password} onChange={(e) => setLoginForm({ ...loginForm, password: e.target.value })} />
            </div>
            <button className="btn-primary full-width" onClick={login}>
              Log In
            </button>
            {message && <div className={`alert alert-${messageType}`}>{message}</div>}
          </div>
        </div>
      </div>
    )
  }

  // Main App
  return (
    <div className="page main-app">
      <header className="top-bar">
        <div className="top-bar-left">
          <h1>🎬 DVDFlix</h1>
        </div>
        <div className="top-bar-center">
          <nav className="nav-tabs">
            {pages.map((p) => (
              <button
                key={p}
                className={`nav-tab ${activePage === p ? 'active' : ''}`}
                onClick={() => setActivePage(p)}
              >
                {p === 'dashboard' && '📊 Dashboard'}
                {p === 'ripper-status' && '⚙️ Ripper'}
                {p === 'settings' && '⚡ Settings'}
                {p === 'library' && '📚 Library'}
                {p === 'history' && '🕘 History'}
                {p === 'accounts' && '👤 Accounts'}
              </button>
            ))}
          </nav>
        </div>
        <div className="top-bar-right">
          <button className="btn-icon" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} title="Toggle theme">
            {theme === 'dark' ? '☀️' : '🌙'}
          </button>
          <button className="btn-secondary" onClick={logout}>Logout</button>
        </div>
      </header>

      {activePage === 'dashboard' && (
        <div className="content">
          <div className="grid-2 grid-gaps">
            <div className="card">
              <h2>🚀 Quick Actions</h2>
              <button className="btn-primary full-width" onClick={startAll}>
                Start All Drives
              </button>
              <div className="drive-buttons">
                {(health?.drives || []).map((d) => (
                  <button key={d} className="btn-secondary" onClick={() => startDrive(d)}>
                    {d}
                  </button>
                ))}
              </div>
            </div>

            <div className="card">
              <h2>📍 System Info</h2>
              <div className="info-list">
                <div className="info-item">
                  <span className="label">Movies Path</span>
                  <span className="value">{health?.movies_path}</span>
                </div>
                <div className="info-item">
                  <span className="label">TV Path</span>
                  <span className="value">{health?.tv_path}</span>
                </div>
                <div className="info-item">
                  <span className="label">Active Drives</span>
                  <span className="value">{health?.drives?.length || 0}</span>
                </div>
              </div>
            </div>
          </div>

          <div className="card">
            <h2>📋 Recent Jobs</h2>
            {jobs.length === 0 ? (
              <p className="empty-state">No jobs yet. Insert a disc to start.</p>
            ) : (
              <div className="jobs-list">
                {jobs.slice(0, 10).map((job) => (
                  <div key={job.id} className="job-item">
                    <div className="job-header">
                      <span className="job-drive">{job.drive}</span>
                      <span className="job-title">{job.title || job.disc_label || 'Unknown'}</span>
                      <span className="job-state" style={{ backgroundColor: jobStateColor(job.state) }}>
                        {job.state}
                      </span>
                    </div>
                    {job.error && <div className="job-error">⚠️ {job.error}</div>}
                    {job.state === 'identifying' && (
                      <button
                        className="btn-secondary"
                        onClick={() => setOverrideModal({ jobId: job.id, jobTitle: job.title || job.disc_label })}
                      >
                        🔍 Search & Override
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'ripper-status' && (
        <div className="content">
          <div className="card">
            <h2>🔧 Ripper Health</h2>
            <div className="health-grid">
              <div className="health-item">
                <span className="label">Overall</span>
                <span className={`badge ${capabilities?.ripper_ready ? 'ok' : 'bad'}`}>
                  {capabilities?.ripper_ready ? '✓ Ready' : '✗ Issues'}
                </span>
              </div>
              <div className="health-item">
                <span className="label">lsdvd</span>
                <span className={`badge ${capabilities?.tools?.lsdvd ? 'ok' : 'bad'}`}>
                  {capabilities?.tools?.lsdvd ? '✓' : '✗'}
                </span>
              </div>
              <div className="health-item">
                <span className="label">makemkvcon</span>
                <span className={`badge ${capabilities?.tools?.makemkvcon ? 'ok' : 'bad'}`}>
                  {capabilities?.tools?.makemkvcon ? '✓' : '✗'}
                </span>
              </div>
              <div className="health-item">
                <span className="label">eject</span>
                <span className={`badge ${capabilities?.tools?.eject ? 'ok' : 'bad'}`}>
                  {capabilities?.tools?.eject ? '✓' : '✗'}
                </span>
              </div>
            </div>
          </div>

          {capabilities?.issues?.length > 0 && (
            <div className="card card-warning">
              <h2>⚠️ Issues</h2>
              <ul>
                {capabilities.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="card">
            <h2>💡 Setup Hints</h2>
            <ul className="hints-list">
              {capabilities?.hints?.map((hint, i) => (
                <li key={i}>{hint}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {activePage === 'settings' && (
        <div className="content">
          <div className="card">
            <h2>⚙️ Runtime Settings</h2>
            {settingsDraft && (
              <>
                <div className="form-grid">
                  <div className="form-group">
                    <label>Movies Path</label>
                    <input value={settingsDraft.MOVIES_PATH || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, MOVIES_PATH: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>TV Path</label>
                    <input value={settingsDraft.TV_PATH || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TV_PATH: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Temp Rip Path</label>
                    <input value={settingsDraft.TEMP_RIP_PATH || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TEMP_RIP_PATH: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Drives (Auto-Detect)</label>
                    <div className="inline-actions">
                      <button type="button" className="btn-secondary" onClick={detectDrives}>
                        Detect Drives
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => setSettingsDraft({ ...settingsDraft, DRIVES: detectedDrives.join(',') })}
                        disabled={detectedDrives.length === 0}
                      >
                        Use Detected
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        onClick={() => setManualSettingsDrives((v) => !v)}
                      >
                        {manualSettingsDrives ? 'Hide Manual Entry' : 'Manual Entry'}
                      </button>
                    </div>
                    {manualSettingsDrives && (
                      <input
                        placeholder="/dev/sr0,/dev/sr1"
                        value={settingsDraft.DRIVES || ''}
                        onChange={(e) => setSettingsDraft({ ...settingsDraft, DRIVES: e.target.value })}
                      />
                    )}
                    <small className="field-help">
                      Current detection: {detectedDrives.length ? detectedDrives.join(', ') : 'none'}
                    </small>
                  </div>
                  <div className="form-group">
                    <label>TMDB API Key</label>
                    <input type="password" value={settingsDraft.TMDB_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TMDB_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>OMDB API Key</label>
                    <input type="password" value={settingsDraft.OMDB_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OMDB_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>TVDB API Key</label>
                    <input type="password" value={settingsDraft.TVDB_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TVDB_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>TVDB PIN</label>
                    <input value={settingsDraft.TVDB_PIN || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, TVDB_PIN: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>OpenSubtitles API Key</label>
                    <input type="password" value={settingsDraft.OPENSUBTITLES_API_KEY || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OPENSUBTITLES_API_KEY: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Ollama URL</label>
                    <input value={settingsDraft.OLLAMA_URL || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OLLAMA_URL: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Ollama Model</label>
                    <input value={settingsDraft.OLLAMA_MODEL || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, OLLAMA_MODEL: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Runtime Tolerance Minutes</label>
                    <input type="number" min="0" max="60" value={settingsDraft.RUNTIME_TOLERANCE_MINUTES || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, RUNTIME_TOLERANCE_MINUTES: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Confidence Threshold</label>
                    <input type="number" min="0" max="100" value={settingsDraft.IDENTIFY_MIN_CONFIDENCE || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, IDENTIFY_MIN_CONFIDENCE: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Max Identify Workers</label>
                    <input type="number" min="1" max="8" value={settingsDraft.MAX_IDENTIFY_WORKERS || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, MAX_IDENTIFY_WORKERS: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Disc Cache DB Path</label>
                    <input value={settingsDraft.DISC_CACHE_DB || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, DISC_CACHE_DB: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>Enable Web Search</label>
                    <select value={settingsDraft.ENABLE_WEB_SEARCH || 'false'} onChange={(e) => setSettingsDraft({ ...settingsDraft, ENABLE_WEB_SEARCH: e.target.value })}>
                      <option value="false">false</option>
                      <option value="true">true</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>Searxng URL</label>
                    <input value={settingsDraft.SEARXNG_URL || ''} onChange={(e) => setSettingsDraft({ ...settingsDraft, SEARXNG_URL: e.target.value })} />
                  </div>
                  <div className="form-group">
                    <label>HandBrake Preset</label>
                    <select value={settingsDraft.HANDBRAKE_PRESET || 'default'} onChange={(e) => setSettingsDraft({ ...settingsDraft, HANDBRAKE_PRESET: e.target.value })}>
                      <option value="default">default (all tracks)</option>
                      <option value="standard">standard (main feature)</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label>MakeMKV Command Path</label>
                    <input value={settingsDraft.MAKEMKVCON_PATH || 'makemkvcon'} onChange={(e) => setSettingsDraft({ ...settingsDraft, MAKEMKVCON_PATH: e.target.value })} />
                  </div>
                </div>
                <button className="btn-primary" onClick={saveSettings}>
                  Save Settings
                </button>
                {message && <div className={`alert alert-${messageType}`}>{message}</div>}
              </>
            )}
          </div>
        </div>
      )}

      {activePage === 'library' && (
        <div className="content">
          <div className="grid-2">
            <div className="card">
              <h2>🎬 Movies ({library.movies.length})</h2>
              <div className="file-list">
                {library.movies.slice(0, 50).map((file, i) => (
                  <div key={i} className="file-item">{file}</div>
                ))}
              </div>
            </div>
            <div className="card">
              <h2>📺 TV Shows ({library.tvshows.length})</h2>
              <div className="file-list">
                {library.tvshows.slice(0, 50).map((file, i) => (
                  <div key={i} className="file-item">{file}</div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {activePage === 'history' && (
        <div className="content">
          <div className="card">
            <h2>🕘 Ripped Disc History ({history.length})</h2>
            {history.length === 0 ? (
              <p className="empty-state">No completed rips have been recorded yet.</p>
            ) : (
              <div className="history-list">
                {history.map((item) => (
                  <div key={item.disc_hash} className="history-item">
                    <div className="history-main">
                      <div className="history-title-row">
                        <span className="job-drive">{item.drive || 'unknown drive'}</span>
                        <span className="job-title">{item.title || item.disc_label || 'Unknown title'}</span>
                        <span className="job-state" style={{ backgroundColor: item.media_type === 'tv' ? '#8b5cf6' : '#10b981' }}>
                          {item.media_type || 'movie'}
                        </span>
                      </div>
                      <div className="history-meta">
                        <span>Disc: {item.disc_label || 'n/a'}</span>
                        <span>Year: {item.year || 'n/a'}</span>
                        <span>Ripped: {item.ripped_at || 'n/a'}</span>
                      </div>
                      {item.output_path && <div className="history-path">{item.output_path}</div>}
                      {item.notes && <div className="history-notes">Notes: {item.notes}</div>}
                    </div>
                    <button
                      className="btn-secondary"
                      onClick={() =>
                        setHistoryEditModal({
                          disc_hash: item.disc_hash,
                          title: item.title || '',
                          year: item.year || '',
                          media_type: item.media_type || 'movie',
                          notes: item.notes || '',
                        })
                      }
                    >
                      Edit Metadata
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {activePage === 'accounts' && (
        <div className="content">
          <div className="grid-2">
            <div className="card">
              <h2>👤 Accounts</h2>
              {currentUser && (
                <p className="field-help">
                  Signed in as <strong>{currentUser.username}</strong>
                  {currentUser.is_admin ? ' (admin)' : ''}
                </p>
              )}
              <div className="history-list">
                {accounts.map((u) => (
                  <div key={u.id} className="history-item">
                    <div className="history-main">
                      <div className="history-title-row">
                        <span className="job-title">{u.username}</span>
                        <span className="job-state" style={{ backgroundColor: u.is_admin ? '#10b981' : '#6b7280' }}>
                          {u.is_admin ? 'admin' : 'user'}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card">
              <h2>➕ Create Account</h2>
              {currentUser?.is_admin ? (
                <>
                  <div className="form-group">
                    <label>Username</label>
                    <input
                      value={newAccountForm.username}
                      onChange={(e) => setNewAccountForm({ ...newAccountForm, username: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Password</label>
                    <input
                      type="password"
                      value={newAccountForm.password}
                      onChange={(e) => setNewAccountForm({ ...newAccountForm, password: e.target.value })}
                    />
                  </div>
                  <div className="form-group">
                    <label>Role</label>
                    <select
                      value={newAccountForm.is_admin ? 'admin' : 'user'}
                      onChange={(e) => setNewAccountForm({ ...newAccountForm, is_admin: e.target.value === 'admin' })}
                    >
                      <option value="user">user</option>
                      <option value="admin">admin</option>
                    </select>
                  </div>
                  <button className="btn-primary" onClick={createAccount}>Create Account</button>
                </>
              ) : (
                <p className="empty-state">Only admin users can create accounts.</p>
              )}
            </div>
          </div>
        </div>
      )}

    {/* Manual Title Override Modal */}
    {overrideModal && (
      <div className="modal-overlay" onClick={() => setOverrideModal(null)}>
        <div className="modal-content" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            <h2>🔍 Search & Override Title</h2>
            <button className="modal-close" onClick={() => setOverrideModal(null)}>✕</button>
          </div>
          
          <div className="modal-body">
            <p className="modal-subtitle">Current: <strong>{overrideModal.jobTitle}</strong></p>
            
            <div className="form-group">
              <label>Search TMDB</label>
              <div className="search-input-group">
                <input
                  type="text"
                  placeholder="Search for title..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && searchQuery.trim()) {
                      searchTMDB(searchQuery.trim())
                    }
                  }}
                />
                <button
                  className="btn-primary"
                  onClick={() => searchQuery.trim() && searchTMDB(searchQuery.trim())}
                  disabled={searching}
                >
                  {searching ? 'Searching...' : 'Search'}
                </button>
              </div>
            </div>

            {searchResults.length > 0 && (
              <div className="search-results">
                <h3>Results:</h3>
                {searchResults.map((result, idx) => (
                  <div key={idx} className="search-result-item">
                    <div className="result-info">
                      <span className="result-title">{result.title}</span>
                      <span className="result-year">{result.release_date?.substring(0, 4)}</span>
                    </div>
                    <button
                      className="btn-secondary"
                      onClick={() =>
                        overrideJobTitle(
                          overrideModal.jobId,
                          result.title,
                          result.release_date?.substring(0, 4) || '',
                          'movie'
                        )
                      }
                    >
                      Select
                    </button>
                  </div>
                ))}
              </div>
            )}

            {searchQuery && !searching && searchResults.length === 0 && (
              <p className="empty-state">No results found. Try a different search.</p>
            )}
          </div>

          <div className="modal-footer">
            <button className="btn-secondary" onClick={() => setOverrideModal(null)}>Close</button>
          </div>
        </div>
      </div>
    )}

    {historyEditModal && (
      <div className="modal-overlay" onClick={() => setHistoryEditModal(null)}>
        <div className="modal-content" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            <h2>✏️ Edit Rip Metadata</h2>
            <button className="modal-close" onClick={() => setHistoryEditModal(null)}>✕</button>
          </div>

          <div className="modal-body">
            <div className="form-group">
              <label>Title</label>
              <input
                value={historyEditModal.title}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, title: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Year</label>
              <input
                value={historyEditModal.year}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, year: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label>Media Type</label>
              <select
                value={historyEditModal.media_type}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, media_type: e.target.value })}
              >
                <option value="movie">movie</option>
                <option value="tv">tv</option>
              </select>
            </div>
            <div className="form-group">
              <label>Notes</label>
              <input
                value={historyEditModal.notes}
                onChange={(e) => setHistoryEditModal({ ...historyEditModal, notes: e.target.value })}
              />
            </div>
          </div>

          <div className="modal-footer">
            <button className="btn-secondary" onClick={() => setHistoryEditModal(null)}>Cancel</button>
            <button className="btn-primary" onClick={saveHistoryCorrection}>Save</button>
          </div>
        </div>
      </div>
    )}
  </div>
  )
}
