import { User } from './user';

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  user: User;
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface SignupRequest {
  email: string;
  name: string;
  password: string;
}

export interface SignupResponse {
  user: User;
  access_token: string;
  refresh_token: string;
  token_type: string;
}
