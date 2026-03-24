import { useEffect, useMemo, useState } from 'react'
import { io } from 'socket.io-client'

const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:7272'
const socketUrl = import.meta.env.VITE_SOCKET_URL || apiUrl

export default function App() {
  const [health, setHealth] = useState(null)
  const [jobs, setJobs] = useState([])
  const [library, setLibrary] = useState({ movies: [], tvshows: [] })

  const socket = useMemo(() => io(socketUrl, { transports: ['websocket', 'polling'] }), [])

  useEffect(() => {
    fetch(`${apiUrl}/api/health`).then((r) => r.json()).then(setHealth)
    fetch(`${apiUrl}/api/jobs`).then((r) => r.json()).then((d) => setJobs(d.jobs || []))
    fetch(`${apiUrl}/api/library`).then((r) => r.json()).then(setLibrary)
  }, [])

  useEffect(() => {
    socket.on('job_update', (job) => {
      setJobs((prev) => {
        const rest = prev.filter((j) => j.id !== job.id)
        return [job, ...rest]
      })
      fetch(`${apiUrl}/api/library`).then((r) => r.json()).then(setLibrary)
    })

    return () => {
      socket.disconnect()
    }
  }, [socket])

  const startAll = async () => {
    await fetch(`${apiUrl}/api/jobs/start-all`, { method: 'POST' })
  }

  const startDrive = async (drive) => {
    await fetch(`${apiUrl}/api/jobs/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ drive }),
    })
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
