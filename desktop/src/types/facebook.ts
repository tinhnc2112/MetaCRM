export type FacebookPage = {
  id: string;
  page_id: string;
  name: string;
  username: string | null;
  picture_url: string | null;
  is_active: boolean;
};

export type FacebookPageListResponse = {
  items: FacebookPage[];
};

export type CurrentFacebookPageResponse = {
  item: FacebookPage | null;
};

export type FacebookAuthUrlResponse = {
  url: string;
};
