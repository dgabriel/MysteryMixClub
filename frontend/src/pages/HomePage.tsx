import React from 'react';
import { useAuth } from '../context/AuthContext';

const HomePage: React.FC = () => {
  const { user } = useAuth();

  return (
    <div className="home-container">
      <h1>Welcome to MysteryMixClub</h1>
      {user && (
        <div className="user-welcome">
          <p>Hello, {user.name}!</p>
          <p className="subtitle">Email: {user.email}</p>
        </div>
      )}
      <div className="feature-section">
        <h2>Coming Soon</h2>
        <ul>
          <li>Create and join music leagues</li>
          <li>Submit songs for themed rounds</li>
          <li>Vote on submissions anonymously</li>
          <li>Compete on leaderboards</li>
          <li>Discover new music</li>
        </ul>
      </div>
    </div>
  );
};

export default HomePage;
