export function WelcomeScreen({ onStart }) {
  return (
    <div className="welcome-screen">
      <h1>Эврика</h1>
      <p>Виртуальный менеджер EdPalm. Помогу подобрать обучение и отвечу по программам.</p>
      <button onClick={onStart}>Начать</button>
    </div>
  )
}
