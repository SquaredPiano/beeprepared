import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Folder, Clock, ChevronRight } from 'lucide-react';
import '../App.css';

export default function ProjectsPage() {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchProjects();
  }, []);

  const fetchProjects = async () => {
    try {
      // Pass a dummy token for now since our backend requires it but verifies loosely in dev
      const res = await fetch('/api/projects', {
        headers: { 'Authorization': 'Bearer test-token' }
      });
      if (!res.ok) throw new Error('Failed to fetch projects');
      const data = await res.json();
      setProjects(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;

    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer test-token'
        },
        body: JSON.stringify({ name: newProjectName })
      });

      if (!res.ok) throw new Error('Failed to create project');
      
      const project = await res.json();
      navigate(`/project/${project.id}`);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="page-container">
      <header className="page-header">
        <h1>My Projects</h1>
        <button className="primary-btn" onClick={() => setShowCreateModal(true)}>
          <Plus size={20} /> New Project
        </button>
      </header>
      
      {error && <div className="error-banner">{error}</div>}

      {loading ? (
        <div className="loading-spinner">Loading...</div>
      ) : (
        <div className="projects-grid">
          {projects.length === 0 ? (
            <div className="empty-state">
              <Folder size={48} opacity={0.5} />
              <p>No projects yet. Create one to get started!</p>
            </div>
          ) : (
            projects.map(p => (
              <div key={p.id} className="project-card" onClick={() => navigate(`/project/${p.id}`)}>
                <div className="card-top">
                  <div className="folder-icon">
                     <Folder size={24} color="#6366f1" />
                  </div>
                  <h3>{p.name}</h3>
                </div>
                <div className="card-bottom">
                  <span className="date">
                    <Clock size={14} /> 
                    {new Date(p.updated_at || p.created_at).toLocaleDateString()}
                  </span>
                  <div className="arrow-icon">
                    <ChevronRight size={20} />
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {showCreateModal && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h2>Create New Project</h2>
            <form onSubmit={handleCreate}>
              <input 
                type="text" 
                placeholder="Project Name (e.g. Biology 101)" 
                value={newProjectName}
                onChange={e => setNewProjectName(e.target.value)}
                autoFocus
              />
              <div className="modal-actions">
                <button type="button" onClick={() => setShowCreateModal(false)} className="secondary-btn">Cancel</button>
                <button type="submit" className="primary-btn" disabled={!newProjectName.trim()}>Create</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
