import HighScoresLibrary from '../components/HighScoresLibrary'

function HighScoresScreen() {
  return (
    <main className="game-screen">
      <section className="panel">
        <h1>High Scores</h1>
        <HighScoresLibrary />
      </section>
    </main>
  )
}

export default HighScoresScreen
